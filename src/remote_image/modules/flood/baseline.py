"""生成有实际文件和来源说明的洪水候选结果。"""
from __future__ import annotations
from pathlib import Path
import geopandas as gpd
import rasterio
from shapely.geometry import Polygon

from remote_image.core.contracts import FloodContext, FloodResult, ResultMeta, SCHEMA_VERSION
from remote_image.core.validation import validate_contract
from .input_io import check_analysis_inputs
from .classification import classify_rasters
from .vectorization import polygonize_mask, export_geojson, verify_vector_mask
from .qa import R2Error, METHOD_VERSION, validate_options, write_json, check_flood_artifacts, sha256_file


def check_extent_boundary(request):
    boundary = Path(request.study_area.boundary)
    if not boundary.is_file():
        raise R2Error("MISSING_INPUT", "研究区边界文件不存在", path=str(boundary))
    area = gpd.read_file(boundary)
    if area.empty or area.crs is None:
        raise R2Error("INVALID_AOI", "研究区必须有几何与 CRS")
    with rasterio.open(request.inputs.post_event.path) as src:
        footprint = Polygon([src.transform * p for p in
                            [(0, 0), (src.width, 0), (src.width, src.height), (0, src.height)]])
        geom = area.to_crs(src.crs).geometry.union_all()
        # 首版只承诺完整输出网格；任意 AOI 必须先显式预处理。
        if geom.symmetric_difference(footprint).area > max(0.01, footprint.area * 1e-10):
            raise R2Error("UNSUPPORTED_AOI", "第一版要求 AOI 与输入矩形范围一致")
    return sha256_file(boundary)


def run_flood_baseline(request):
    validate_contract(request)
    threshold = validate_options(request.options)
    checked = check_analysis_inputs(request.inputs)
    boundary_sha = check_extent_boundary(request)
    out = Path(request.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if any((out / name).exists() for name in ("flood_mask.tif", "flood_result.json", "metadata.json")):
        raise R2Error("OUTPUT_EXISTS", "运行目录已有结果，请使用新目录", output=str(out))
    counts = classify_rasters(
        request.inputs.pre_event.path, request.inputs.post_event.path,
        request.inputs.valid_mask, threshold, request.options.min_patch_area_m2 or 0,
        out / "flood_mask.tif", permanent_water_mask=request.options.permanent_water_mask,
        exclusion_mask=request.options.exclusion_mask)
    warnings = ["新增低散射水体候选；识别精度尚未经过独立参考验证。",
                "输入是 gamma0 dB；当前团队 sigma0 规格的正式兼容性待审阅。"]
    if request.options.permanent_water_mask is None:
        warnings.append("未使用永久水体辅助资料，仅按本次灾前影像排除已有水体。")
    params = {
        "radiometry": {"quantity": "gamma0", "scale": "db", "polarization": "VV"},
        "water_threshold_db": threshold, "comparison": "<", "connectivity": 4,
        "min_patch_area_m2": request.options.min_patch_area_m2 or 0,
        "aoi_kind": "raster_extent", "aoi_sha256": boundary_sha,
        "run_id": out.name, "class_values": {"not_detected": 0, "candidate": 1, "unknown": 255},
        "permanent_water_mask": str(request.options.permanent_water_mask) if request.options.permanent_water_mask else None,
        "exclusion_mask": str(request.options.exclusion_mask) if request.options.exclusion_mask else None,
        "input_analysis_sha256": {"pre": sha256_file(request.inputs.pre_event.path),
                                 "post": sha256_file(request.inputs.post_event.path),
                                 "valid_mask": sha256_file(request.inputs.valid_mask)},
        "counts": counts,
    }
    meta = ResultMeta(SCHEMA_VERSION, request.event_id, request.study_area.identifier,
                      (request.inputs.pre_event.asset_id, request.inputs.post_event.asset_id),
                      "sar_post_threshold", METHOD_VERSION, parameters=params, warnings=tuple(warnings))
    ctx = FloodContext(meta.event_id, meta.study_area_id, meta.method, meta.method_version,
                       params, request.inputs.post_event.coordinate_reference_system)
    polygonize_mask(out / "flood_mask.tif", ctx, out / "flood_polygons.gpkg")
    export_geojson(out / "flood_polygons.gpkg", out / "flood_polygons.geojson")
    spatial = verify_vector_mask(out / "flood_mask.tif", out / "flood_polygons.gpkg")
    write_json(out / "validation" / "spatial_qa.json", spatial)
    write_json(out / "validation" / "analysis_input_check.json", checked)
    write_json(out / "metadata.json", meta)
    result = FloodResult({"flood_mask": out / "flood_mask.tif",
                          "flood_polygons": out / "flood_polygons.gpkg",
                          "metadata": out / "metadata.json",
                          "flood_polygons_geojson": out / "flood_polygons.geojson"}, meta)
    write_json(out / "flood_result.json", result)
    write_json(out / "validation" / "artifact_check.json", check_flood_artifacts(result))
    return result
