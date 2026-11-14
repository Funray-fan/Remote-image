"""R3 阶段二辅助图层复核；不推断建筑损毁或道路通行状态。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from remote_image.core.contracts import CheckItem, ContextLayers, ContextQAReport, StudyArea
from remote_image.core.serialization import from_payload, to_payload
from remote_image.core.validation import validate_contract
from remote_image.modules.decision.stage1 import (
    _BUILDING_KEYS, _POPULATION_KEYS, _RASTER_SUFFIXES, _ROAD_KEYS,
    _VECTOR_SUFFIXES, _check, _load_area, _overall_status,
    _require_geopandas, _require_rasterio,
)


def validate_context_layers(
    layers: ContextLayers,
    event_id: str,
    *,
    area: StudyArea | None = None,
) -> ContextQAReport:
    """复核阶段一图层能否交给当前事件的阶段二流程。

    不传 ``area`` 时只能确认事件 ID、文件、来源、几何与图层范围；
    缺少当前事件边界时，不能声称覆盖已验证。独立 xBD 事件必须用自己的
    ContextLayers，不能复用涿州图层并仅修改 event_id。
    """
    if not event_id.strip():
        raise ValueError("event_id 不能为空")
    checks: list[CheckItem] = []
    warnings: list[str] = []
    metrics: dict[str, object] = {"layer_count": len(layers.layers)}
    checks.append(_check("event_id", "pass" if layers.event_id == event_id else "fail",
                         event_id, layers.event_id, "图层事件与请求一致" if layers.event_id == event_id else "不能复用另一事件的基础图层"))
    checks.append(_check("sources.event_id", "pass" if layers.sources.event_id == event_id else "fail",
                         event_id, layers.sources.event_id, "来源事件与请求一致" if layers.sources.event_id == event_id else "来源清单属于另一事件"))
    if area is None:
        checks.append(_check("study_area_id", "pass" if layers.study_area_id.strip() else "fail",
                             "非空研究区 ID", layers.study_area_id,
                             "研究区 ID 已记录" if layers.study_area_id.strip() else "研究区 ID 缺失"))
    if area is None:
        warnings.append("未提供当前事件研究区边界；无法验证图层覆盖当前事件，仅报告图层自身范围")
        checks.append(_check("event_coverage", "warning", "当前事件研究区边界", None, warnings[-1]))
        area_geometry = None
    else:
        checks.append(_check("study_area_id", "pass" if layers.study_area_id == area.identifier else "fail",
                             area.identifier, layers.study_area_id, "研究区 ID 一致" if layers.study_area_id == area.identifier else "研究区 ID 不一致"))
        area_frame = _load_area(area).to_crs(layers.target_crs)
        area_geometry = area_frame.geometry.iloc[0]

    keys = set(layers.layers)
    source_keys = set(layers.sources.layers)
    checks.append(_check("source_keys", "pass" if keys == source_keys else "fail",
                         sorted(keys), sorted(source_keys), "图层与来源一一对应" if keys == source_keys else "图层与来源记录不一致"))
    building_keys = {key for key in keys if key.casefold() in _BUILDING_KEYS}
    road_keys = {key for key in keys if key.casefold() in _ROAD_KEYS}
    for name, present in (("building_layer", bool(building_keys)), ("road_layer", bool(road_keys))):
        checks.append(_check(name, "pass" if present else "fail", True, present,
                             "必需底图已提供" if present else "缺少必需底图"))
    if not any(key.casefold() in _POPULATION_KEYS for key in keys):
        warnings.append("缺少人口图层；人口暴露应保持未知")
        checks.append(_check("population_layer", "warning", "人口图层或缺失说明", None, warnings[-1]))

    for key, raw_path in sorted(layers.layers.items()):
        record = layers.sources.layers.get(key)
        if record is None:
            checks.append(_check(f"{key}.source_record", "fail", "SourceRecord", None, "缺少来源记录"))
            continue
        provenance_ok = bool(record.source.strip() and record.license_id.strip())
        checks.append(_check(f"{key}.provenance", "pass" if provenance_ok else "fail",
                             "来源和许可非空", {"source": record.source, "license_id": record.license_id},
                             "来源和许可已记录" if provenance_ok else "来源或许可缺失"))
        if record.date is None:
            warnings.append(f"{key} 的来源观测日期未知，无法确认与当前事件的时间一致性")
            checks.append(_check(f"{key}.date", "warning", "带时区的观测日期", None, warnings[-1]))
        else:
            checks.append(_check(f"{key}.date", "pass", "带时区的观测日期",
                                 record.date.isoformat(), "来源观测日期已记录；仍需人工核对与事件的时间关系"))
        path = Path(raw_path).expanduser().resolve()
        recorded_path = record.path.expanduser().resolve()
        checks.append(_check(f"{key}.source_path", "pass" if recorded_path == path else "fail",
                             str(path), str(recorded_path),
                             "来源记录对应当前交接文件" if recorded_path == path else "来源记录与交接文件路径不一致"))
        if not path.is_file():
            checks.append(_check(f"{key}.file", "fail", "可读取文件", str(path), "图层文件不存在"))
            continue
        try:
            if path.suffix.lower() in _VECTOR_SUFFIXES:
                gpd = _require_geopandas()
                frame = gpd.read_file(path)
                crs = frame.crs
                crs_ok = crs is not None and crs == gpd.GeoSeries([], crs=layers.target_crs).crs
                valid = frame.geometry.notna() & ~frame.geometry.is_empty & frame.geometry.is_valid
                valid_count = int(valid.sum())
                geom_ok = valid_count == len(frame) and valid_count > 0
                if key in building_keys:
                    geom_ok = geom_ok and frame.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all()
                if key in road_keys:
                    geom_ok = geom_ok and frame.geometry.geom_type.isin(["LineString", "MultiLineString"]).all()
                bounds = [float(value) for value in frame.total_bounds] if valid_count else None
                covered = bool(valid_count and area_geometry is not None and frame.loc[valid].geometry.intersects(area_geometry).any())
                count = len(frame)
                id_values = frame[record.id_field] if record.id_field in frame.columns else None
            elif path.suffix.lower() in _RASTER_SUFFIXES:
                rasterio = _require_rasterio()
                from rasterio.crs import CRS
                from shapely.geometry import box
                with rasterio.open(path) as dataset:
                    crs = dataset.crs
                    crs_ok = crs is not None and crs == CRS.from_string(layers.target_crs)
                    bounds = [float(value) for value in dataset.bounds]
                    geom_ok = dataset.width > 0 and dataset.height > 0 and dataset.count > 0
                    covered = bool(area_geometry is not None and box(*bounds).intersects(area_geometry))
                    count = dataset.width * dataset.height
                id_values = None
            else:
                raise ValueError(f"不支持的图层格式: {path.suffix}")
        except Exception as error:
            checks.append(_check(f"{key}.read", "fail", "可读取的 GIS 图层", type(error).__name__, str(error)))
            continue
        checks.append(_check(f"{key}.crs", "pass" if crs_ok else "fail",
                             layers.target_crs, str(crs), "CRS 一致" if crs_ok else "CRS 缺失或不一致"))
        checks.append(_check(f"{key}.geometry", "pass" if geom_ok else "fail",
                             "非空且有效的对应类型几何", bool(geom_ok), "几何可用" if geom_ok else "几何为空、无效或类型不符"))
        metrics[f"{key}.feature_or_pixel_count"] = count
        metrics[f"{key}.bounds"] = bounds
        if area_geometry is not None:
            if path.suffix.lower() in _RASTER_SUFFIXES and covered:
                message = f"{key} 的栅格外包框与研究区相交，尚未检查有效像元覆盖"
                warnings.append(message)
                coverage_status = "warning"
            else:
                message = "图层覆盖当前研究区的一部分" if covered else "图层未覆盖当前研究区"
                coverage_status = "pass" if covered else "fail"
            checks.append(_check(f"{key}.coverage", coverage_status,
                                 "与当前事件研究区相交", covered, message))
        if key in building_keys | road_keys:
            if not record.id_field or id_values is None:
                checks.append(_check(f"{key}.object_ids", "fail", "已声明且存在的 ID 字段",
                                     record.id_field, "建筑/道路对象 ID 字段缺失"))
            else:
                ids = id_values.astype(str).str.strip()
                invalid = int(id_values.isna().sum() + ids.eq("").sum())
                duplicates = int(ids[~id_values.isna()].duplicated().sum())
                ok = invalid == 0 and duplicates == 0
                metrics[f"{key}.duplicate_id_count"] = duplicates
                checks.append(_check(f"{key}.object_ids", "pass" if ok else "fail",
                                     {"invalid": 0, "duplicates": 0},
                                     {"invalid": invalid, "duplicates": duplicates},
                                     "对象 ID 完整且唯一" if ok else "对象 ID 有空值或重复"))

    manifest = next(iter(layers.layers.values())).parent / "context_layers.json" if layers.layers else None
    report = ContextQAReport(
        status=_overall_status(checks), checks=tuple(checks), metrics=metrics,
        warnings=tuple(warnings),
        artifacts={"context_layers": manifest} if manifest is not None and manifest.is_file() else {},
    )
    validate_contract(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="R3 阶段二基础图层复核")
    parser.add_argument("--context", type=Path, required=True, help="阶段一 context_layers.json")
    parser.add_argument("--event-id", required=True, help="当前阶段二事件 ID")
    parser.add_argument("--area-boundary", help="当前事件边界文件或 WKT；提供后可验证空间覆盖")
    parser.add_argument("--area-id", help="当前事件研究区 ID")
    parser.add_argument("--area-crs", help="当前事件研究区 CRS")
    parser.add_argument("--output", type=Path, required=True, help="输出 context_qa.json")
    args = parser.parse_args()
    if bool(args.area_boundary) != bool(args.area_id) or bool(args.area_boundary) != bool(args.area_crs):
        parser.error("--area-boundary、--area-id、--area-crs 必须同时提供")
    layers = from_payload(ContextLayers, json.loads(args.context.read_text(encoding="utf-8")))
    area = StudyArea(args.area_id, args.area_boundary, args.area_crs) if args.area_boundary else None
    report = validate_context_layers(layers, args.event_id, area=area)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(to_payload(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report.status, "output": str(args.output),
                      "failed_checks": [item.name for item in report.checks if item.status == "fail"]}, ensure_ascii=False))
    return 1 if report.status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
