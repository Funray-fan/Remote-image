"""R2 本地命令入口：检查输入、比较参数、复跑案例。"""
from __future__ import annotations
import argparse
import dataclasses
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from shapely.geometry import box, Polygon, mapping

from remote_image.core.contracts import (PreparedInputs, FloodOptions, FloodRequest, StudyArea,
    ContextLayers, ContextSources, SourceRecord, LayerManifest, MapLayerSpec, ThresholdReport)
from remote_image.core.serialization import from_payload, to_payload
from remote_image.core.validation import validate_contract
from .input_io import prepare_analysis_inputs, inspect_linear_inputs, check_analysis_inputs, CONVERSION_VERSION
from .qa import R2Error, read_json, write_json, sha256_file, check_flood_artifacts
from .thresholds import evaluate_candidates
from .baseline import run_flood_baseline
from .exposure import summarize_exposure

LOG=logging.getLogger("remote_image.r2")


def load_config(path):
    path=Path(path).resolve()
    cfg=read_json(path)
    root=(path.parent/cfg.get("project_root","../..")).resolve()
    cfg["_project_root"]=str(root)
    cfg["_config_path"]=str(path)
    declaration=cfg["input"]
    if (declaration.get("backscatter_quantity"),declaration.get("value_scale"),declaration.get("polarization")) != ("gamma0","linear_power","VV"):
        raise R2Error("RADIOMETRY_UNDECLARED","案例入口要求明确 gamma0/linear_power/VV")
    if cfg["analysis"].get("connectivity") != 4 or cfg["analysis"].get("aoi_kind") != "raster_extent":
        raise R2Error("UNSUPPORTED_CONFIGURATION","首版固定四邻域和输入矩形范围")
    return cfg


def resolve(cfg, value):
    if value is None:
        return None
    path=Path(value)
    return path.resolve() if path.is_absolute() else (Path(cfg["_project_root"])/path).resolve()


def _raw_paths(cfg):
    item=cfg["input"]
    return [resolve(cfg,item[key]) for key in ("prepared_inputs_path","pre_path","post_path","valid_mask_path")]


def cache_fingerprint(hashes, manifest_hash, source_revision):
    body={"inputs":hashes,"manifest":manifest_hash,"conversion":CONVERSION_VERSION,
          "source_revision":source_revision}
    return hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()[:20]


def snapshot_config(cfg, destination):
    saved={k:v for k,v in cfg.items() if not k.startswith("_")}
    saved["project_root"]=os.path.relpath(cfg["_project_root"],Path(destination).parent).replace(chr(92),"/")
    return saved


def validate_selection(cfg, option):
    selection=cfg.get("selection",{})
    path=resolve(cfg,selection.get("evaluation_report"))
    if path is None:
        return None
    if not path.is_file():
        raise R2Error("MISSING_SELECTION_REPORT","冻结配置引用的参数报告不存在",path=str(path))
    report=from_payload(ThresholdReport,read_json(path))
    if to_payload(report.selected_options)!=to_payload(option):
        raise R2Error("STALE_SELECTION","本次参数与比较报告不同，请重新 evaluate 冻结参数")
    return path


def prepared_for_config(cfg):
    manifest,pre,post,mask=_raw_paths(cfg)
    observed=inspect_linear_inputs(pre,post,mask,cfg["input"].get("expected"))
    hashes={key:sha256_file(path) for key,path in zip(("pre_event","post_event","valid_mask"),(pre,post,mask))}
    expected=cfg["input"].get("expected_hashes",{})
    if any(hashes.get(k)!=v for k,v in expected.items()):
        raise R2Error("HASH_MISMATCH","原始文件校验值与配置不符")
    key=cache_fingerprint(hashes,sha256_file(manifest),cfg["input"].get("source_revision"))
    cache=Path(cfg["_project_root"])/"work"/"r2"/"prepared"/key
    cache_record=cache/"cache_validation.json"
    if cache_record.exists():
        record=read_json(cache_record)
        for name,sha in record["outputs"].items():
            if not (cache/name).is_file() or sha256_file(cache/name)!=sha:
                raise R2Error("CACHE_MISMATCH","派生缓存被改动",file=name)
        payload=read_json(cache/"prepared_inputs.json")
        for name in ("pre_event","post_event"):
            payload[name]["path"]=str((cache/payload[name]["path"]).resolve())
        payload["valid_mask"]=str((cache/payload["valid_mask"]).resolve())
        inputs=from_payload(PreparedInputs,payload)
        check_analysis_inputs(inputs)
        provenance=read_json(cache/"input_provenance.json")
    else:
        inputs,provenance=prepare_analysis_inputs(manifest,pre,post,mask,cache,
            source_revision=cfg["input"].get("source_revision"),expected_hashes=expected)
        names=["pre_event_db.tif","post_event_db.tif","valid_mask.tif","prepared_inputs.json","input_provenance.json"]
        write_json(cache_record,{"inputs":hashes,"outputs":{name:sha256_file(cache/name) for name in names}})
    return inputs,provenance,observed


def options(cfg,threshold=None,min_patch=None):
    analysis=cfg["analysis"]
    threshold=analysis.get("selected_water_threshold_db") if threshold is None else threshold
    if threshold is None:
        raise R2Error("UNSELECTED_THRESHOLD","先执行 evaluate，或在配置中明确选择试运行阈值")
    return FloodOptions(("VV",),{"VV":threshold},{"VV":threshold},"single",
        resolve(cfg,analysis.get("permanent_water_mask")),resolve(cfg,analysis.get("exclusion_mask")),
        analysis.get("min_patch_area_m2",0) if min_patch is None else min_patch)


def development_region(cfg,inputs):
    with rasterio.open(inputs.post_event.path) as src:
        shape,transform=src.shape,src.transform
    regions=cfg["threshold_search"].get("development_bounds",[])
    heldout=cfg["threshold_search"].get("heldout_bounds",[])
    if not regions or not heldout:
        raise R2Error("MISSING_REGIONS","案例必须声明开发区与留出区")
    dev=geometry_mask([mapping(box(*r)) for r in regions],shape,transform,invert=True)
    test=geometry_mask([mapping(box(*r)) for r in heldout],shape,transform,invert=True)
    if not dev.any() or not test.any() or (dev & test).any():
        raise R2Error("REGION_OVERLAP","开发区和留出区必须非空且不相交")
    return dev


def _stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")


def evaluate(cfg):
    inputs,_,_=prepared_for_config(cfg)
    candidates=[options(cfg,t,a) for t in cfg["threshold_search"]["candidate_values_db"]
        for a in cfg["threshold_search"].get("candidate_patch_areas_m2",[0])]
    out=Path(cfg["_project_root"])/"work"/"r2"/"evaluations"/_stamp()
    report=evaluate_candidates(inputs,candidates,resolve(cfg,cfg["threshold_search"].get("reference_path")),
                              out,development_region(cfg,inputs))
    from .preview import render_preview
    bounds=cfg["threshold_search"]["development_bounds"][0]
    for i,item in enumerate(candidates):
        render_preview(inputs,report.artifacts[f"candidate_{i}"],out/f"candidate_{i:02d}.png",bounds,
                       f"Development only | T={item.post_thresholds_db['VV']} dB | min patch={item.min_patch_area_m2} m2")
    frozen={k:v for k,v in cfg.items() if not k.startswith("_")}
    frozen["analysis"]=dict(frozen["analysis"])
    frozen["analysis"]["selected_water_threshold_db"]=report.selected_options.post_thresholds_db["VV"]
    frozen["analysis"]["min_patch_area_m2"]=report.selected_options.min_patch_area_m2
    frozen["selection"]={"status":"provisional_without_reference" if not report.reference_available else "selected_on_development",
                         "reason":report.selection_reason,
                         "evaluation_report":str((out/"threshold_report.json").relative_to(cfg["_project_root"])).replace("\\","/"),
                         "reference_available":report.reference_available}
    resolved=Path(cfg["_config_path"]).with_name(Path(cfg["_config_path"]).stem.replace(".resolved","")+".resolved.json")
    write_json(resolved,frozen)
    return {"resolved_config":str(resolved),"threshold_report":str(out/"threshold_report.json"),
            "selected_threshold_db":report.selected_options.post_thresholds_db["VV"],
            "selected_min_patch_area_m2":report.selected_options.min_patch_area_m2,
            "reference_available":report.reference_available}


def context_for_run(cfg,out):
    paths,records,mappings={},{},{}
    target=out/"context";target.mkdir()
    for kind in ("buildings","roads"):
        source=resolve(cfg,cfg.get("context",{}).get(kind+"_path"))
        if source is None:
            continue
        if not source.is_file():
            raise R2Error("MISSING_CONTEXT_LAYER","配置中的图层不存在",layer=kind,path=str(source))
        expected=cfg["context"].get("expected_hashes",{}).get(kind)
        if expected and sha256_file(source)!=expected:
            raise R2Error("HASH_MISMATCH","上下文图层与固定来源不符",layer=kind)
        frame=gpd.read_file(source)
        if frame.crs is None:
            raise R2Error("MISSING_CRS","背景图层缺少 CRS",layer=kind)
        rule=cfg["context"].get("id_rule","osm_type:osm_id")
        if rule!="osm_type:osm_id" or not {"osm_type","osm_id"} <= set(frame.columns):
            raise R2Error("MISSING_ID","案例适配需要 osm_type 与 osm_id")
        if frame[["osm_type","osm_id"]].isna().any().any():
            raise R2Error("MISSING_ID","OSM 对象 ID 缺失")
        def osm_id(value):
            if isinstance(value,(int,np.integer)): return str(int(value))
            if isinstance(value,(float,np.floating)) and float(value).is_integer(): return str(int(value))
            return str(value)
        frame["source_id"]=frame["osm_type"].astype(str)+":"+frame["osm_id"].map(osm_id)
        file=target/(kind+".gpkg")
        # 分析只携带身份和几何，原始属性保留在固定来源文件。
        frame[["source_id","osm_type","osm_id","geometry"]].to_file(file,layer=kind,driver="GPKG",engine="pyogrio",index=False)
        paths[kind]=file
        records[kind]=SourceRecord(file,"OpenStreetMap / fixed R1 repository snapshot",None,"ODbL-1.0","source_id")
        mappings[kind]={"source_path":str(source),"source_sha256":sha256_file(source),
                        "id_rule":rule,"feature_count":len(frame),"observation_date":None,
                        "limitation":"Not a verified 2023 historical or complete inventory."}
    write_json(target/"source_mapping.json",mappings)
    layers=ContextLayers(cfg["event_id"],cfg["event_id"],cfg["analysis"]["area_crs"],paths,
                         ContextSources(cfg["event_id"],records))
    validate_contract(layers);write_json(target/"context_layers.json",layers)
    return layers


def _git_info(root):
    def command(*args):
        return subprocess.check_output(["git",*args],cwd=root,text=True,encoding="utf-8").strip()
    return {"commit":command("rev-parse","HEAD"),"branch":command("branch","--show-current"),
            "working_tree_dirty":bool(command("status","--porcelain")),
            "python":platform.python_version(),
            "source_sha256":{str(p.relative_to(root)).replace(chr(92),"/"):sha256_file(p) for p in sorted((Path(root)/"src"/"remote_image").rglob("*.py"))}}


def run(cfg,run_id=None):
    started=time.monotonic()
    option=options(cfg)
    selected_report_path=validate_selection(cfg,option)
    run_id=run_id or _stamp()
    if Path(run_id).name!=run_id or run_id in (".","..") or any(c in run_id for c in "\\/:"):
        raise R2Error("INVALID_RUN_ID","run-id 必须是单个目录名")
    out=resolve(cfg,cfg["output"]["root"])/run_id
    if out.exists():
        raise R2Error("OUTPUT_EXISTS","请使用新的 run-id",path=str(out))
    out.mkdir(parents=True)
    handler=logging.FileHandler(out/"run.log",encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.addHandler(handler);LOG.setLevel(logging.INFO)
    try:
        LOG.info("输入预检与派生输入")
        inputs,provenance,checked=prepared_for_config(cfg)
        copied=out/"prepared";shutil.copytree(inputs.post_event.path.parent,copied)
        payload=read_json(copied/"prepared_inputs.json")
        for key in ("pre_event","post_event"):
            payload[key]["path"]=str((copied/payload[key]["path"]).resolve())
        payload["valid_mask"]=str((copied/payload["valid_mask"]).resolve())
        inputs=from_payload(PreparedInputs,payload)
        write_json(out/"validation"/"input_check.json",checked)
        with rasterio.open(inputs.post_event.path) as src:
            geom=Polygon([src.transform*p for p in [(0,0),(src.width,0),(src.width,src.height),(0,src.height)]])
            boundary=out/"study_area.geojson"
            gpd.GeoDataFrame({"id":[cfg["event_id"]]},geometry=[geom],crs=src.crs).to_crs(4326).to_file(
                boundary,driver="GeoJSON",engine="pyogrio",layer_options={"COORDINATE_PRECISION":"15"})
        area=StudyArea(cfg["event_id"],str(boundary),"EPSG:4326")
        LOG.info("分类与转面：T=%s dB，面积门槛=%s m2",option.post_thresholds_db["VV"],option.min_patch_area_m2)
        result=run_flood_baseline(FloodRequest(cfg["event_id"],area,inputs,option,out))
        LOG.info("准备背景图层与暴露统计")
        context=context_for_run(cfg,out)
        exposure=summarize_exposure(result,context,cfg["analysis"]["area_crs"])
        manifest_layers=[
            MapLayerSpec("pre_event",cfg["event_id"],"raster",inputs.pre_event.path,inputs.pre_event.coordinate_reference_system,(inputs.pre_event.asset_id,),"灾前 gamma0 dB",{"min":-25,"max":5}),
            MapLayerSpec("post_event",cfg["event_id"],"raster",inputs.post_event.path,inputs.post_event.coordinate_reference_system,(inputs.post_event.asset_id,),"灾后 gamma0 dB",{"min":-25,"max":5}),
            MapLayerSpec("flood_mask",cfg["event_id"],"raster",result.artifacts["flood_mask"],inputs.post_event.coordinate_reference_system,result.meta.input_asset_ids,"新增水体候选",{"classes":{"0":"not_detected","1":"candidate","255":"unknown"}}),
            MapLayerSpec("flood_polygons",cfg["event_id"],"vector",result.artifacts["flood_polygons_geojson"],"EPSG:4326",result.meta.input_asset_ids,"候选范围",{"color":"#0072B2"})]
        for kind,path in context.layers.items():
            display=out/"context"/(kind+".geojson")
            gpd.read_file(path,layer=kind).to_crs(4326).to_file(display,driver="GeoJSON",engine="pyogrio",layer_options={"COORDINATE_PRECISION":"15"})
            manifest_layers.append(MapLayerSpec(kind,cfg["event_id"],"vector",display,"EPSG:4326",(),kind,{}))
        manifest=LayerManifest(cfg["event_id"],tuple(manifest_layers))
        validate_contract(manifest);write_json(out/"layer_manifest.json",manifest)
        from .preview import render_preview
        if cfg["output"].get("write_previews",True):
            render_preview(inputs,result.artifacts["flood_mask"],out/"previews"/"overview.png",
                title=f"Zhuozhou | T={option.post_thresholds_db['VV']} dB | min patch={option.min_patch_area_m2} m2")
            render_preview(inputs,result.artifacts["flood_mask"],out/"previews"/"development_comparison.png",
                           cfg["threshold_search"]["development_bounds"][0])
        selection=cfg.get("selection",{})
        threshold_source=selected_report_path
        if threshold_source and threshold_source.is_file():
            # 留存完整比较表；报告中的候选栅格仍可追溯到工作目录。
            shutil.copy2(threshold_source,out/"threshold_report.json")
            table=threshold_source.parent/"threshold_candidates.csv"
            if table.exists(): shutil.copy2(table,out/"threshold_candidates.csv")
        write_json(out/"selected_options.json",option)
        write_json(out/"resolved_config.json",snapshot_config(cfg,out/"resolved_config.json"))
        write_json(out/"validation"/"evaluation.json",{"status":"not_validated","precision":None,"recall":None,
            "f1":None,"iou":None,"reason":"No independent date-matched held-out reference evaluation has been performed.",
            "selection":selection,"heldout_bounds":cfg["threshold_search"]["heldout_bounds"]})
        missing=[kind for kind in ("buildings","roads") if kind not in context.layers]
        summary={"engineering_status":"pass","case_run_status":"partial" if missing else "complete",
                 "scientific_validation_status":"not_validated","integration_status":"ready_for_review",
                 "event_id":cfg["event_id"],"run_id":run_id,"output_dir":str(out),"elapsed_seconds":round(time.monotonic()-started,3),
                 "method":"sar_post_threshold","method_version":result.meta.method_version,
                 "parameters":{"water_threshold_db":option.post_thresholds_db["VV"],"min_patch_area_m2":option.min_patch_area_m2},
                 "metrics":exposure.metrics,"units":exposure.units,"missing_layers":missing,
                 "source_revision":cfg["input"]["source_revision"],"code":_git_info(cfg["_project_root"]),
                 "input_hashes":{k:v["sha256"] for k,v in provenance["source_files"].items()},
                 "warnings":list(dict.fromkeys([*result.meta.warnings,*exposure.warnings]))}
        check_flood_artifacts(result)
        for layer in manifest.layers:
            if not layer.path.is_file(): raise R2Error("MISSING_ARTIFACT","地图清单指向缺失文件",path=str(layer.path))
        write_json(out/"summary.json",summary)
        write_json(out/"run_status.json",{"status":"complete","summary":"summary.json"})
        LOG.info("运行完成，科学精度尚未验证")
        return summary
    except Exception as exc:
        LOG.exception("运行失败")
        write_json(out/"run_status.json",{"status":"failed","error":exc.as_dict() if isinstance(exc,R2Error) else {"type":type(exc).__name__,"message":str(exc)}})
        raise
    finally:
        LOG.removeHandler(handler);handler.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("check","evaluate","run"))
    parser.add_argument("--config",required=True,type=Path)
    parser.add_argument("--run-id")
    args=parser.parse_args(argv)
    try:
        cfg=load_config(args.config)
        work=Path(cfg["_project_root"])/"work"
        for name in ("temp","matplotlib"): (work/name).mkdir(parents=True,exist_ok=True)
        os.environ["MPLCONFIGDIR"]=str(work/"matplotlib")
        if args.command=="check":
            _,provenance,checked=prepared_for_config(cfg)
            output=work/"r2"/"input_check.json";write_json(output,checked)
            result={"status":checked["status"],"report":str(output),"counts":checked["counts"],"warnings":provenance["warnings"]}
        elif args.command=="evaluate": result=evaluate(cfg)
        else:
            summary=run(cfg,args.run_id)
            result={"status":summary["case_run_status"],"output_dir":summary["output_dir"],
                    "candidate_area_km2":summary["metrics"]["candidate_area_m2"]/1e6,
                    "building_source_objects_intersecting":summary["metrics"]["building_objects_intersecting"],
                    "road_overlap_km":None if summary["metrics"]["road_overlap_length_m"] is None else summary["metrics"]["road_overlap_length_m"]/1000,
                    "scientific_validation_status":summary["scientific_validation_status"],
                    "summary_path":str(Path(summary["output_dir"])/"summary.json")}
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        return 0
    except Exception as exc:
        error=exc.as_dict() if isinstance(exc,R2Error) else {"code":type(exc).__name__,"message":str(exc)}
        print(json.dumps({"status":"failed","error":error},ensure_ascii=False,indent=2),file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
