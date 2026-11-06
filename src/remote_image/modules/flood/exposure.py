"""候选范围与来源建筑、道路的精确交叠，不推断结构损毁或通行状态。"""
from __future__ import annotations

import csv
import math
from dataclasses import replace
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import rasterio
from pyproj import CRS
from rasterio.features import shapes
from shapely import STRtree, union_all
from shapely.geometry import Polygon, shape
from shapely.validation import explain_validity

from remote_image.core.contracts import ContextLayers, ExposureReport, FloodResult, utc_now
from .qa import METHOD_VERSION, R2Error, read_json, sha256_file, write_json

AREA_TOLERANCE_M2 = 1e-6
LENGTH_TOLERANCE_M = 1e-6
RELATIVE_TOLERANCE = 1e-9


def _metric_crs(value):
    try:
        crs = CRS.from_user_input(value)
    except Exception as exc:
        raise R2Error("INVALID_CRS", "面积统计坐标系无法识别", crs=str(value)) from exc
    if not crs.is_projected or crs.to_epsg() == 3857 or not crs.axis_info or any(
        not math.isclose(axis.unit_conversion_factor, 1.0, abs_tol=1e-12)
        for axis in crs.axis_info[:2]
    ):
        raise R2Error("INVALID_CRS", "面积与长度统计要求以米为单位的投影坐标系", crs=str(value))
    return crs


def _require_file(path, label):
    path = Path(path)
    if not path.is_file():
        raise R2Error("MISSING_INPUT", "找不到统计所需文件", layer=label, path=str(path))
    return path


def _project_geometries(geometries, source_crs, target_crs):
    if not geometries:
        return []
    return list(gpd.GeoSeries(geometries, crs=source_crs).to_crs(target_crs))


def _mask_extent(mask_path, area_crs):
    with rasterio.open(mask_path) as ds:
        if ds.crs is None:
            raise R2Error("MISSING_CRS", "候选掩膜没有 CRS", path=str(mask_path))
        values = ds.read(1)
        if ds.dtypes[0] != "uint8" or ds.nodata != 255:
            raise R2Error("INVALID_MASK", "最终候选掩膜要求 uint8、NoData=255")
        if ds.count != 1 or not np.isin(values, [0, 1, 255]).all():
            raise R2Error("INVALID_MASK", "最终候选掩膜只能包含 0、1、255")
        transform = ds.transform
        if not all(math.isfinite(v) for v in transform) or abs(transform.determinant) == 0:
            raise R2Error("INVALID_GRID", "候选掩膜仿射变换无效")
        observed = values != 255
        observed_shapes = [shape(geom) for geom, _ in shapes(
            observed.astype("uint8"), mask=observed, transform=transform, connectivity=4
        )]
        projected = _project_geometries(observed_shapes, ds.crs, area_crs)
        extent = Polygon([(transform.a * x + transform.b * y + transform.c,
                           transform.d * x + transform.e * y + transform.f)
                          for x, y in [(0, 0), (ds.width, 0), (ds.width, ds.height), (0, ds.height)]])
        extent = _project_geometries([extent], ds.crs, area_crs)[0]
        if not observed.any():
            raise R2Error("NO_VALID_DATA", "最终掩膜没有可观察区域，不能作为零候选结果")
        return projected, extent, int((values == 1).sum())


def _read_candidates(path, event_id, area_crs, candidate_pixels):
    frame = gpd.read_file(path, layer="flood_polygons")
    if frame.crs is None:
        raise R2Error("MISSING_CRS", "候选面图层没有 CRS", path=str(path))
    if "event_id" in frame and any(str(v) != event_id for v in frame["event_id"]):
        raise R2Error("EVENT_MISMATCH", "候选面与洪水结果事件不同")
    for index, geometry in enumerate(frame.geometry):
        if geometry is None or geometry.is_empty or not geometry.is_valid or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise R2Error("INVALID_GEOMETRY", "候选面包含不可用几何", row=index)
    if bool(len(frame)) != bool(candidate_pixels):
        raise R2Error("ARTIFACT_MISMATCH", "候选像元与候选面空状态不一致")
    return list(frame.to_crs(area_crs).geometry)


class _SpatialMeasure:
    """先查空间索引，再对候选片段精确相交并合并，避免重复累计。"""
    def __init__(self, geometries):
        self.geometries = list(geometries)
        self.tree = STRtree(self.geometries)

    def overlap(self, geometry, measure):
        indices = self.tree.query(geometry)
        pieces = [geometry.intersection(self.geometries[int(i)]) for i in indices]
        pieces = [part for part in pieces if not part.is_empty]
        if not pieces:
            return 0.0
        combined = union_all(pieces)
        return float(combined.area if measure == "area" else combined.length)

    def area(self):
        return float(union_all(self.geometries).area) if self.geometries else 0.0


def _same_geometry(left, right):
    if left is None or right is None:
        return left is None and right is None
    try:
        return bool(left.equals(right))
    except Exception:
        return left.wkb == right.wkb


def _empty_frame(kind, crs):
    measure = "building_area_m2" if kind == "buildings" else "road_length_m"
    observed = "observed_area_m2" if kind == "buildings" else "observed_length_m"
    overlap = "candidate_overlap_m2" if kind == "buildings" else "candidate_overlap_length_m"
    data = {"source_id": pd.Series(dtype="str"), "source_id_field": pd.Series(dtype="str"),
            measure: pd.Series(dtype="float64"), observed: pd.Series(dtype="float64"),
            overlap: pd.Series(dtype="float64"),
            "overlap_fraction_of_total": pd.Series(dtype="float64"),
            "overlap_fraction_of_observed": pd.Series(dtype="float64"),
            "observed_status": pd.Series(dtype="str"),
            "candidate_exposed": pd.Series(dtype="boolean"),
            "outside_raster_area_m2" if kind == "buildings" else "outside_raster_length_m": pd.Series(dtype="float64"),
            "unknown_within_raster_area_m2" if kind == "buildings" else "unknown_within_raster_length_m": pd.Series(dtype="float64")}
    return gpd.GeoDataFrame(data, geometry=gpd.GeoSeries([], crs=crs), crs=crs)


def _source_features(kind, path, record, event_id, area_crs):
    frame = gpd.read_file(path)
    if frame.crs is None:
        raise R2Error("MISSING_CRS", "来源图层没有 CRS", layer=kind, path=str(path))
    id_field = record.id_field
    if not id_field or id_field not in frame.columns:
        raise R2Error("MISSING_ID", "来源图层必须声明实际存在的稳定 ID 字段", layer=kind, id_field=id_field)
    if "event_id" in frame and any(str(v) != event_id for v in frame["event_id"]):
        raise R2Error("EVENT_MISMATCH", "来源要素事件不同", layer=kind)
    seen, selected, issues = {}, [], []
    duplicates = 0
    allowed = {"Polygon", "MultiPolygon"} if kind == "buildings" else {"LineString", "MultiLineString"}
    for index, row in frame.iterrows():
        raw_id, geometry = row[id_field], row.geometry
        if geometry is None or not hasattr(geometry, "geom_type") and pd.isna(geometry):
            geometry = None
        if pd.isna(raw_id) or isinstance(raw_id, (bool, np.bool_)) or not str(raw_id).strip():
            raise R2Error("MISSING_ID", "来源对象的稳定 ID 为空或无效", layer=kind, row=str(index))
        source_id = str(raw_id)
        if source_id in seen:
            if not _same_geometry(seen[source_id], geometry):
                raise R2Error("DUPLICATE_ID_CONFLICT", "同一来源 ID 对应不同几何，须由数据负责人确认", layer=kind, source_id=source_id)
            duplicates += 1
            continue
        seen[source_id] = geometry
        reason = None
        if geometry is None:
            reason = "missing_geometry"
        elif geometry.is_empty:
            reason = "empty_geometry"
        elif geometry.geom_type not in allowed:
            reason = "unsupported_geometry_type: " + geometry.geom_type
        elif not geometry.is_valid:
            reason = "invalid_geometry: " + explain_validity(geometry)
        elif (geometry.area if kind == "buildings" else geometry.length) <= 0:
            reason = "zero_measure_geometry"
        if reason:
            issues.append({"layer": kind, "source_id": source_id, "source_row": str(index), "reason": reason})
        else:
            selected.append({"source_id": source_id, "geometry": geometry})
    valid = gpd.GeoDataFrame(selected, geometry="geometry", crs=frame.crs) if selected else gpd.GeoDataFrame(
        {"source_id": pd.Series(dtype="str")}, geometry=gpd.GeoSeries([], crs=frame.crs), crs=frame.crs)
    valid = valid.to_crs(area_crs)
    projected_invalid = ~valid.geometry.is_valid | valid.geometry.is_empty
    for _, row in valid[projected_invalid].iterrows():
        issues.append({"layer": kind, "source_id": row.source_id, "source_row": "projected", "reason": "invalid_after_reprojection"})
    valid = valid[~projected_invalid]
    return valid, issues, {"input_rows": len(frame), "unique_source_ids": len(seen),
                            "duplicate_rows_removed": duplicates, "invalid_objects": len(issues), "valid_objects": len(valid)}


def _measure_layer(kind, frame, id_field, observed, candidates, extent, crs):
    records = []
    area = kind == "buildings"
    tolerance = AREA_TOLERANCE_M2 if area else LENGTH_TOLERANCE_M
    measure = "area" if area else "length"
    for _, row in frame.iterrows():
        geometry = row.geometry
        total = float(geometry.area if area else geometry.length)
        inside = geometry.intersection(extent)
        inside_measure = float(inside.area if area else inside.length)
        observed_measure = min(total, max(0.0, observed.overlap(geometry, measure)))
        full_tolerance = max(tolerance, total * RELATIVE_TOLERANCE)
        if observed_measure <= tolerance:
            status, overlap, exposed, fraction_total, fraction_observed = "unobserved", None, None, None, None
        else:
            status = "complete" if total - observed_measure <= full_tolerance else "partial"
            overlap = min(observed_measure, max(0.0, candidates.overlap(geometry, measure)))
            overlap = 0.0 if overlap <= tolerance else overlap
            exposed = True if overlap > tolerance else (False if status == "complete" else None)
            fraction_total = overlap / total if status == "complete" else None
            fraction_observed = overlap / observed_measure
        record = {"source_id": row.source_id, "source_id_field": id_field,
                  "building_area_m2" if area else "road_length_m": total,
                  "observed_area_m2" if area else "observed_length_m": observed_measure,
                  "candidate_overlap_m2" if area else "candidate_overlap_length_m": overlap,
                  "overlap_fraction_of_total": fraction_total,
                  "overlap_fraction_of_observed": fraction_observed,
                  "observed_status": status, "candidate_exposed": exposed,
                  "outside_raster_area_m2" if area else "outside_raster_length_m": max(0.0, total - inside_measure),
                  "unknown_within_raster_area_m2" if area else "unknown_within_raster_length_m": max(0.0, inside_measure - observed_measure),
                  "geometry": geometry}
        records.append(record)
    result = gpd.GeoDataFrame(records, geometry="geometry", crs=crs) if records else _empty_frame(kind, crs)
    result["candidate_exposed"] = pd.array(result["candidate_exposed"], dtype="boolean")
    return result


def _csv_value(value):
    if value is None or value is pd.NA or isinstance(value, (float, np.floating)) and math.isnan(value):
        return ""
    if isinstance(value, (bool, np.bool_)):
        return "true" if value else "false"
    return value


def _write_rows(path, columns, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in columns})


def summarize_exposure(flood: FloodResult, layers: ContextLayers, area_crs: str) -> ExposureReport:
    """统计候选交叠；部分或缺失观测不当作已确认零暴露。"""
    if layers.event_id != flood.meta.event_id or layers.sources.event_id != flood.meta.event_id:
        raise R2Error("EVENT_MISMATCH", "洪水结果与上下文事件不同")
    if layers.study_area_id != flood.meta.study_area_id:
        raise R2Error("STUDY_AREA_MISMATCH", "洪水结果与上下文研究区不同")
    crs = _metric_crs(area_crs)
    required = {"flood_mask", "flood_polygons", "metadata"}
    if required - flood.artifacts.keys():
        raise R2Error("MISSING_ARTIFACT", "洪水结果缺少暴露统计所需产物", missing=sorted(required - flood.artifacts.keys()))
    files = {key: _require_file(flood.artifacts[key], key) for key in required}
    metadata = read_json(files["metadata"])
    for key in ("event_id", "study_area_id"):
        if metadata.get(key) != getattr(flood.meta, key):
            raise R2Error("EVENT_MISMATCH", "洪水元数据与结果对象不一致", field=key)
    observed_geometries, extent, candidate_pixels = _mask_extent(files["flood_mask"], crs)
    candidate_geometries = _read_candidates(files["flood_polygons"], flood.meta.event_id, crs, candidate_pixels)
    observed, candidates = _SpatialMeasure(observed_geometries), _SpatialMeasure(candidate_geometries)
    metrics = {"candidate_area_m2": candidates.area(), "observed_area_m2": observed.area(),
               "unknown_area_m2": max(0.0, float(extent.area) - observed.area()),
               "building_objects_intersecting": None, "building_overlap_area_m2": None,
               "road_overlap_length_m": None, "population_exposed": None}
    units = {name: "m2" for name in ("candidate_area_m2", "observed_area_m2", "unknown_area_m2", "building_overlap_area_m2")}
    units.update(building_objects_intersecting="source_objects", road_overlap_length_m="m", population_exposed="people")
    warnings = [*flood.meta.warnings, "人口暴露未实现或无合格输入，population_exposed 为 null；候选交叠不表示建筑结构损毁或道路阻断。"]
    frames, issues, details, source_metadata = {}, [], {}, {}
    for kind, prefix in (("buildings", "building"), ("roads", "road")):
        if kind not in layers.layers or layers.layers[kind] is None:
            frames[kind] = _empty_frame(kind, crs)
            details[kind] = {"status": "not_available"}
            warnings.append(f"未提供 {kind} 图层，相应统计为 null。")
            for suffix in ("objects_total", "objects_observed", "objects_unknown", "objects_invalid"):
                metrics[f"{prefix}_{suffix}"] = None
                units[f"{prefix}_{suffix}"] = "source_objects"
            continue
        path = _require_file(layers.layers[kind], kind)
        if kind not in layers.sources.layers:
            raise R2Error("MISSING_SOURCE", "图层缺少来源记录", layer=kind)
        record = layers.sources.layers[kind]
        if not record.source or not record.license_id:
            raise R2Error("MISSING_SOURCE", "图层来源与许可必须填写", layer=kind)
        if Path(record.path).resolve() != path.resolve():
            raise R2Error("SOURCE_PATH_MISMATCH", "图层路径与来源记录不一致", layer=kind)
        if record.date is None:
            warnings.append(f"{kind} 来源日期未知，历史事件的年代一致性未验证。")
        valid, layer_issues, detail = _source_features(kind, path, record, flood.meta.event_id, crs)
        frame = _measure_layer(kind, valid, record.id_field, observed, candidates, extent, crs)
        frames[kind] = frame
        issues.extend(layer_issues)
        details[kind] = {"status": "warning" if layer_issues else "pass", **detail}
        source_metadata[kind] = {"path": str(path), "source": record.source, "date": record.date.isoformat() if record.date else None,
                                 "license_id": record.license_id, "id_field": record.id_field,
                                 "sha256": sha256_file(path)}
        unknown_count = int(frame["candidate_exposed"].isna().sum()) + len(layer_issues)
        metrics.update({f"{prefix}_objects_total": detail["unique_source_ids"],
                        f"{prefix}_objects_observed": int((frame["observed_status"] != "unobserved").sum()),
                        f"{prefix}_objects_unknown": unknown_count,
                        f"{prefix}_objects_invalid": len(layer_issues)})
        for suffix in ("objects_total", "objects_observed", "objects_unknown", "objects_invalid"):
            units[f"{prefix}_{suffix}"] = "source_objects"
        usable_layer = bool(len(frame)) or not detail["unique_source_ids"]
        if kind == "buildings":
            metrics["building_objects_intersecting"] = int(frame["candidate_exposed"].fillna(False).sum()) if usable_layer else None
            metrics["building_overlap_area_m2"] = float(frame["candidate_overlap_m2"].sum()) if usable_layer and (frame["candidate_overlap_m2"].notna().any() or not len(frame)) else None
        else:
            metrics["road_overlap_length_m"] = float(frame["candidate_overlap_length_m"].sum()) if usable_layer and (frame["candidate_overlap_length_m"].notna().any() or not len(frame)) else None
        if layer_issues:
            warnings.append(f"{kind} 有 {len(layer_issues)} 个无法定位或几何不可用对象，未纳入交叠，原因见 exposure_geometry_issues.csv。")
        if detail["duplicate_rows_removed"]:
            warnings.append(f"{kind} 去除 {detail['duplicate_rows_removed']} 行同 ID 同几何重复记录。")
    output_dir = files["metadata"].parent
    gpkg_path = output_dir / "exposure_features.gpkg"
    if gpkg_path.exists():
        gpkg_path.unlink()
    for kind, frame in frames.items():
        pyogrio.write_dataframe(frame, gpkg_path, layer=kind, driver="GPKG",
                                geometry_type="MultiPolygon" if kind == "buildings" else "MultiLineString",
                                promote_to_multi=True)
        columns = [name for name in frame.columns if name != "geometry"]
        _write_rows(output_dir / f"exposure_{kind}.csv", columns, frame.drop(columns="geometry").to_dict("records"))
    issues_path = output_dir / "exposure_geometry_issues.csv"
    _write_rows(issues_path, ["layer", "source_id", "source_row", "reason"], issues)
    statistics_path = output_dir / "exposure.csv"
    _write_rows(statistics_path, ["metric", "value", "unit"],
                [{"metric": key, "value": value, "unit": units[key]} for key, value in metrics.items()])
    warnings = tuple(dict.fromkeys(warnings))
    meta = replace(flood.meta, method="r2_candidate_exposure", method_version=METHOD_VERSION,
                   created_at=utc_now(), warnings=warnings,
                   parameters={**flood.meta.parameters, "area_crs": crs.to_string(),
                               "area_tolerance_m2": AREA_TOLERANCE_M2,
                               "length_tolerance_m": LENGTH_TOLERANCE_M,
                               "relative_tolerance": RELATIVE_TOLERANCE,
                               "observed_status_values": ["complete", "partial", "unobserved"],
                               "observation_rule": "final_flood_mask != 255",
                               "building_overlap_aggregation": "sum_over_distinct_source_ids_not_union_across_buildings",
                               "null_csv_representation": "empty_field", "sources": source_metadata,
                               "quality_report": str(output_dir / "exposure_qa.json")})
    report = ExposureReport(meta, statistics_path, gpkg_path, metrics, units, warnings)
    write_json(output_dir / "exposure_qa.json", {"status": "warning" if warnings else "pass",
               "layers": details, "geometry_issue_count": len(issues),
               "geometry_issues_path": issues_path, "warnings": warnings})
    write_json(output_dir / "exposure_report.json", report)
    return report
