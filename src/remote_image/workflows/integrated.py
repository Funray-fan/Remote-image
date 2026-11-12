"""Executable stage-one integration of R1/R3/R2/C2 and the C3 map handoff."""
from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import rasterio
from shapely.geometry import box

from remote_image.core.contracts import (
    StudyArea, SourceRecord, ContextSources, FloodRequest, DamageRequest,
    MapLayerSpec, LayerManifest, PipelineRunResult,
)
from remote_image.core.manifest import build_manifest
from remote_image.core.validation import validate_contract, validate_result
from remote_image.modules.data import r1_preprocessing as r1
from remote_image.modules.decision.stage1 import prepare_context_layers, validate_context_layers
from remote_image.modules.damage.baseline_adapter import EmptyBaselineDamageAdapter
from remote_image.modules.flood import cli as r2
from remote_image.modules.flood.baseline import run_flood_baseline
from remote_image.modules.flood.exposure import summarize_exposure
from remote_image.modules.flood.qa import read_json, write_json, check_flood_artifacts


ROOT = Path(__file__).resolve().parents[3]


def run_case(config_path: str | Path, *, root: Path | None = None) -> Path:
    """Run registered gamma0 inputs. Scientific accuracy remains unvalidated."""
    started = datetime.now(timezone.utc)
    cfg = r2.load_config(config_path)
    project = Path(cfg['_project_root']) if root is None else Path(root).resolve()
    cfg['_project_root'] = str(project)
    run_id = started.strftime('%Y%m%dT%H%M%S_%fZ')
    out = project / 'outputs' / cfg['event_id'] / 'stage1' / 'integrated' / run_id
    out.mkdir(parents=True)
    write_json(out / 'run_status.json', {'status': 'running'})
    try:
        result = _run(cfg, project, out, run_id, started)
        write_json(out / 'run_status.json', {'status': 'complete', 'engineering_status': 'pass',
                                          'pipeline_status': result.status})
        return out
    except Exception as error:
        write_json(out / 'run_status.json', {'status': 'failed', 'error': str(error)})
        raise


def _run(cfg, project, out, run_id, started):
    inputs, provenance, inspected = r2.prepared_for_config(cfg)
    # Copy analysis inputs so the result does not depend on a disposable cache.
    shutil.copytree(inputs.post_event.path.parent, out / 'prepared')
    inputs = replace(inputs,
        pre_event=replace(inputs.pre_event, path=out/'prepared'/inputs.pre_event.path.name),
        post_event=replace(inputs.post_event, path=out/'prepared'/inputs.post_event.path.name),
        valid_mask=out/'prepared'/inputs.valid_mask.name)
    with rasterio.open(inputs.post_event.path) as ds:
        footprint, crs = box(*ds.bounds), ds.crs.to_string()
    boundary = out/'study_area.gpkg'
    gpd.GeoDataFrame({'id':[inputs.study_area_id]}, geometry=[footprint], crs=crs).to_file(boundary, driver='GPKG')
    area = StudyArea(inputs.study_area_id, str(boundary), crs)
    legacy_area = r1.StudyArea(area.identifier, {'bbox': list(footprint.bounds)}, crs)
    reports = {}
    for name, raw_path in [('pre', cfg['input']['pre_path']), ('post', cfg['input']['post_path'])]:
        raw = r1.raster_asset_from_path(r2.resolve(cfg, raw_path), name, 'registered gamma0 source', ('VV',))
        report = r1.validate_raster(raw, legacy_area, ('VV',))
        r1.write_report(report, out/f'r1_{name}_validation.json')
        reports['r1_'+name] = out/f'r1_{name}_validation.json'
        if report.status == 'fail':
            raise ValueError(f'R1 {name} raster validation failed')
    write_json(out/'input_check.json', inspected)
    sources = {}
    normalized = out/'source_context'
    normalized.mkdir()
    for kind in ('buildings', 'roads'):
        source = r2.resolve(cfg, cfg['context'][kind+'_path'])
        expected = cfg['context'].get('expected_hashes', {}).get(kind)
        if expected and r2.sha256_file(source) != expected:
            raise ValueError(f'{kind} source hash mismatch')
        frame = gpd.read_file(source)
        if frame[['osm_type', 'osm_id']].isna().any().any():
            raise ValueError(f'{kind} missing source identity')
        def identity(value):
            return str(int(value)) if isinstance(value, (int, float)) and float(value).is_integer() else str(value)
        frame['source_id'] = frame.osm_type.astype(str)+':'+frame.osm_id.map(identity)
        path = normalized/(kind+'.gpkg')
        frame[['source_id', 'geometry']].to_file(path, driver='GPKG', layer=kind, index=False)
        sources[kind] = SourceRecord(path, cfg.get('context_source', 'OpenStreetMap contributors / fixed R1 snapshot'),
            None, 'ODbL-1.0' if not cfg.get('synthetic') else 'synthetic fixture', 'source_id')
    context = prepare_context_layers(area, ContextSources(cfg['event_id'], sources), crs, out/'context')
    context_qa = validate_context_layers(context, area)
    write_json(out/'context_qa.json', context_qa)
    reports['context_qa'] = out/'context_qa.json'
    if context_qa.status == 'fail':
        raise ValueError('R3 context QA failed: '+str([c.message for c in context_qa.checks if c.status=='fail']))
    flood = run_flood_baseline(FloodRequest(cfg['event_id'], area, inputs, r2.options(cfg), out/'flood'))
    validate_contract(flood)
    if validate_result(flood)['status'] != 'pass':
        raise ValueError('Flood artifact files failed validation')
    check_flood_artifacts(flood)
    exposure = summarize_exposure(flood, context, crs)
    validate_contract(exposure)
    # C2 is explicitly an empty adapter integration check, never a damage estimate.
    adapter = EmptyBaselineDamageAdapter(output_root=out/'adapter_check')
    damage = adapter.predict(DamageRequest(event_id=cfg['event_id'], study_area=area,
        pre_event=inputs.pre_event, post_event=inputs.post_event,
        model_name=adapter.name, model_version=adapter.version, task='building_damage'))
    validate_contract(damage)
    layers = [
        MapLayerSpec('pre_event', cfg['event_id'], 'raster', inputs.pre_event.path, crs,
                     (inputs.pre_event.asset_id,), '灾前 gamma0 dB'),
        MapLayerSpec('post_event', cfg['event_id'], 'raster', inputs.post_event.path, crs,
                     (inputs.post_event.asset_id,), '灾后 gamma0 dB'),
        MapLayerSpec('flood_mask', cfg['event_id'], 'raster', flood.artifacts['flood_mask'], crs,
                     flood.meta.input_asset_ids, '新增水体候选'),
        MapLayerSpec('flood_polygons', cfg['event_id'], 'vector', flood.artifacts['flood_polygons'], crs,
                     flood.meta.input_asset_ids, '新增水体候选范围', {'color':'#087e8b'}),
    ]
    for kind, path in context.layers.items():
        layers.append(MapLayerSpec(kind, cfg['event_id'], 'vector', path, crs, (),
            '建筑底图' if kind=='buildings' else '道路底图',
            {'color':'#d49826' if kind=='buildings' else '#526878'}))
    manifest = LayerManifest(cfg['event_id'], tuple(layers))
    validate_contract(manifest)
    # Public paths are relative to the manifest, so the case folder can be moved intact.
    import os
    manifest = replace(manifest, layers=tuple(replace(l, path=Path(os.path.relpath(l.path, out))) for l in manifest.layers))
    write_json(out/'layer_manifest.json', manifest)
    warnings = list(dict.fromkeys([*flood.meta.warnings, *context_qa.warnings, *exposure.warnings,
        '无独立参考标签，Precision/Recall/F1/IoU 未验证。',
        'C2 仅完成空基线接口检查，未运行建筑损毁识别。']))
    summary = {'event_id':cfg['event_id'], 'synthetic':bool(cfg.get('synthetic')),
        'engineering_status':'pass', 'scientific_validation_status':'not_validated',
        'integration_status':'complete', 'method':flood.meta.method,
        'method_version':flood.meta.method_version, 'created_at':datetime.now(timezone.utc).isoformat(),
        'metrics':exposure.metrics, 'units':exposure.units, 'warnings':warnings,
        'parameters':{'water_threshold_db':cfg['analysis']['selected_water_threshold_db']},
        'accuracy':dict.fromkeys(['precision','recall','f1','iou']),
        'steps':['R1 raster check','R2 gamma0 conversion','R3 context and QA',
                 'R2 flood/vector/exposure','C2 empty adapter check','C3 map handoff']}
    write_json(out/'summary.json', summary)
    write_json(out/'resolved_config.json', r2.snapshot_config(cfg, out/'resolved_config.json'))
    artifacts = {**flood.artifacts, 'layer_manifest':out/'layer_manifest.json',
                 'summary':out/'summary.json', 'exposure':exposure.statistics_path}
    result = PipelineRunResult(run_id, 'partial', cfg['event_id'], 'stage1', artifacts,
        reports, started, datetime.now(timezone.utc), tuple(warnings))
    validate_contract(result)
    write_json(out/'pipeline_result.json', result)
    # Retain the existing v1 checksum ledger only as a documented legacy auxiliary file.
    build_manifest(event_id=cfg['event_id'], stage='stage1', input_asset_ids=flood.meta.input_asset_ids,
        method=flood.meta.method, artifacts={**artifacts, **reports, 'pipeline_result':out/'pipeline_result.json'},
        output_path=out/'file_manifest.json', project_root=project,
        schema_path=ROOT/'schemas/v1/stage-result-manifest.schema.json',
        run_command='python -m remote_image.workflows.integrated --config '+str(Path(cfg['_config_path']).relative_to(project)),
        tests=[{'name':'runtime_contract_and_artifact_checks','status':'pass'}], warnings=warnings)
    return result


def main():
    parser = argparse.ArgumentParser(description='阶段一整合运行')
    parser.add_argument('--config', default='configs/integrated-zhuozhou.json')
    args = parser.parse_args()
    print(run_case(args.config))


if __name__ == '__main__':
    main()
