"""四邻域候选转面、分析文件导出及像元一致性检查。"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pyogrio
import rasterio
from rasterio.features import rasterize, shapes
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union
from shapely.validation import explain_validity

from remote_image.core.contracts import FloodContext
from .classification import _validate_codes, pixel_area_m2
from .qa import R2Error

LAYER_NAME = "flood_polygons"


def _read_mask(mask_path):
    path = Path(mask_path)
    if not path.is_file():
        raise R2Error("MISSING_INPUT", "找不到分类掩膜", path=str(path))
    with rasterio.open(path) as source:
        if source.count != 1 or source.crs is None:
            raise R2Error("INVALID_MASK", "分类掩膜必须为有 CRS 的单波段栅格")
        values = source.read(1)
        _validate_codes(values, (0, 1, 255), path)
        # 分类编码必须与文件的有效性声明一致，不能把隐藏的候选像元转成面。
        if np.any((values == 1) & (source.read_masks(1) == 0)):
            raise R2Error("INVALID_MASK", "候选像元被文件掩膜声明为无效", path=str(path))
        area = pixel_area_m2(source)
        return values, source.crs, source.transform, area


def _destination(output_path):
    path = Path(output_path)
    if path.suffix.lower() not in {".gpkg", ".geojson"}:
        raise R2Error("UNSUPPORTED_FORMAT", "矢量输出仅支持 .gpkg 和 .geojson", path=str(path))
    if path.exists():
        raise R2Error("OUTPUT_EXISTS", "输出文件已存在，请使用新的运行目录", path=str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _polygon_parts(geometry):
    if isinstance(geometry, Polygon):
        return [geometry] if not geometry.is_empty else []
    if hasattr(geometry, "geoms"):
        return [part for child in geometry.geoms for part in _polygon_parts(child)]
    return []


def _empty_frame(crs):
    fields = {
        "candidate_id": np.empty(0, dtype=object),
        "event_id": np.empty(0, dtype=object),
        "run_id": np.empty(0, dtype=object),
        "method": np.empty(0, dtype=object),
        "method_version": np.empty(0, dtype=object),
        "pixel_count": np.empty(0, dtype=np.int64),
        "area_m2": np.empty(0, dtype=np.float64),
        "geometry_repaired": np.empty(0, dtype=bool),
        "repair_area_delta_m2": np.empty(0, dtype=np.float64),
        "repair_note": np.empty(0, dtype=object),
    }
    return gpd.GeoDataFrame(fields, geometry=gpd.GeoSeries([], crs=crs), crs=crs)


def _write_frame(frame, path):
    if path.suffix.lower() == ".gpkg":
        pyogrio.write_dataframe(frame, path, layer=LAYER_NAME, driver="GPKG",
                                geometry_type="MultiPolygon", promote_to_multi=True)
    else:
        geographic = frame.to_crs("EPSG:4326")
        pyogrio.write_dataframe(geographic, path, driver="GeoJSON",
                                geometry_type="MultiPolygon", promote_to_multi=True,
                                layer_options={"RFC7946": "YES", "COORDINATE_PRECISION": "15"})


def _load_vector(path):
    path = Path(path)
    if not path.is_file():
        raise R2Error("MISSING_INPUT", "找不到矢量文件", path=str(path))
    if path.suffix.lower() == ".gpkg":
        frame = gpd.read_file(path, layer=LAYER_NAME, engine="pyogrio")
    elif path.suffix.lower() == ".geojson":
        frame = gpd.read_file(path, engine="pyogrio")
    else:
        raise R2Error("UNSUPPORTED_FORMAT", "矢量输入仅支持 .gpkg 和 .geojson")
    if frame.crs is None:
        raise R2Error("INVALID_AREA_CRS", "矢量文件缺少 CRS", path=str(path))
    if frame.geometry.isna().any() or frame.geometry.is_empty.any() or (~frame.geometry.is_valid).any():
        raise R2Error("INVALID_GEOMETRY", "矢量中包含空、缺失或无效几何", path=str(path))
    if not frame.empty and not frame.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise R2Error("INVALID_GEOMETRY", "洪水候选图层只能包含面", path=str(path))
    return frame


def polygonize_mask(mask_path, ctx: FloodContext, output_path) -> Path:
    """保留分析网格边界；GPKG 留在源投影，GeoJSON 转成经纬度。"""
    values, crs, transform, area = _read_mask(mask_path)
    output = _destination(output_path)
    requested_crs = rasterio.crs.CRS.from_user_input(ctx.output_crs)
    if output.suffix.lower() == ".gpkg" and requested_crs != crs:
        raise R2Error("GRID_MISMATCH", "分析 GPKG 的 output_crs 必须与分类掩膜投影一致",
                      expected=crs.to_string(), actual=ctx.output_crs)
    if output.suffix.lower() == ".geojson" and requested_crs not in (crs, rasterio.crs.CRS.from_epsg(4326)):
        raise R2Error("INVALID_AREA_CRS", "GeoJSON 上下文 CRS 必须为分析投影或 EPSG:4326")
    _, unit_factor = crs.linear_units_factor
    square_factor = unit_factor * unit_factor
    run_id = str(ctx.parameters.get("run_id") or output.parent.name)
    rows = []
    for index, (geojson, _) in enumerate(shapes(values, mask=values == 1,
                                               transform=transform, connectivity=4), start=1):
        geometry = shape(geojson)
        original_area = float(geometry.area * square_factor)
        repaired = not geometry.is_valid
        repair_note = ""
        if repaired:
            repair_note = explain_validity(geometry)
            fixed = make_valid(geometry)
            parts = _polygon_parts(fixed)
            if not parts:
                raise R2Error("INVALID_GEOMETRY", "修复后没有有效的面", candidate=index)
            geometry = unary_union(parts)
        if geometry.is_empty or not geometry.is_valid:
            raise R2Error("INVALID_GEOMETRY", "候选面无法修复为有效几何", candidate=index)
        measured_area = float(geometry.area * square_factor)
        tolerance = max(1e-6, original_area * 1e-9)
        if abs(measured_area - original_area) > tolerance:
            raise R2Error("ARTIFACT_MISMATCH", "几何修复改变了候选面积", candidate=index,
                          before_m2=original_area, after_m2=measured_area)
        pixel_count = int(round(measured_area / area))
        if abs(measured_area - pixel_count * area) > max(1e-6, measured_area * 1e-9):
            raise R2Error("ARTIFACT_MISMATCH", "面面积不是像元面积的整数倍", candidate=index)
        if isinstance(geometry, Polygon):
            geometry = MultiPolygon([geometry])
        if not isinstance(geometry, MultiPolygon):
            raise R2Error("INVALID_GEOMETRY", "修复结果含非面几何", candidate=index)
        rows.append({"candidate_id": f"{run_id}:candidate:{index:08d}",
                     "event_id": ctx.event_id, "run_id": run_id, "method": ctx.method,
                     "method_version": ctx.method_version, "pixel_count": pixel_count,
                     "area_m2": measured_area, "geometry_repaired": repaired,
                     "repair_area_delta_m2": measured_area - original_area,
                     "repair_note": repair_note, "geometry": geometry})
    frame = gpd.GeoDataFrame(rows, geometry="geometry", crs=crs) if rows else _empty_frame(crs)
    _write_frame(frame, output)
    verify_vector_mask(mask_path, output)
    return output


def export_geojson(gpkg_path, output_path) -> Path:
    """导出展示文件，面积字段仍保留分析投影中的平方米。"""
    source = Path(gpkg_path)
    if source.suffix.lower() != ".gpkg":
        raise R2Error("UNSUPPORTED_FORMAT", "展示导出要求以分析 GPKG 为输入")
    output = _destination(output_path)
    if output.suffix.lower() != ".geojson":
        raise R2Error("UNSUPPORTED_FORMAT", "展示导出的路径必须为 .geojson")
    frame = _load_vector(source)
    _write_frame(frame, output)
    return output


def verify_vector_mask(mask_path, vector_path) -> dict:
    """回栅格核对类别，并独立核对几何面积与属性面积。"""
    values, crs, transform, pixel_area = _read_mask(mask_path)
    frame = _load_vector(vector_path).to_crs(crs)
    if frame.empty:
        burned = np.zeros(values.shape, dtype=np.uint8)
    else:
        burned = rasterize(((mapping(geom), 1) for geom in frame.geometry),
                           out_shape=values.shape, transform=transform, fill=0,
                           all_touched=False, dtype="uint8")
    expected = values == 1
    mismatches = int(np.count_nonzero((burned == 1) != expected))
    expected_area = int(np.count_nonzero(expected)) * pixel_area
    _, unit_factor = crs.linear_units_factor
    measured_area = float(frame.geometry.area.sum() * unit_factor * unit_factor)
    # GeoJSON 的 WGS84 往返投影允许微小浮点面积差，类别仍要求逐像元一致。
    tolerance = max(1e-4, expected_area * 1e-8)
    area_difference = measured_area - expected_area
    properties_area = float(frame["area_m2"].sum()) if "area_m2" in frame else (0.0 if frame.empty else None)
    report = {"status": "pass", "feature_count": len(frame),
              "candidate_pixels": int(np.count_nonzero(expected)),
              "rasterized_candidate_pixels": int(np.count_nonzero(burned == 1)),
              "mismatch_pixels": mismatches, "expected_area_m2": expected_area,
              "vector_area_m2": measured_area, "area_difference_m2": area_difference,
              "area_tolerance_m2": tolerance, "properties_area_m2": properties_area}
    if (mismatches or abs(area_difference) > tolerance
            or properties_area is None or not np.isfinite(properties_area)
            or abs(properties_area - expected_area) > tolerance):
        raise R2Error("ARTIFACT_MISMATCH", "候选面与分类掩膜不一致", **report)
    return report
