"""R3 阶段一基础图层标准化与道路网络质量检查。"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from remote_image.core.contracts import (
    CheckItem,
    ContextLayers,
    ContextQAReport,
    ContextSources,
    NetworkReport,
    NetworkSpec,
    QualityStatus,
    SourceRecord,
    StudyArea,
)
from remote_image.core.serialization import to_payload
from remote_image.core.validation import validate_contract


_VECTOR_SUFFIXES = {".geojson", ".json", ".gpkg", ".shp", ".fgb", ".parquet"}
_RASTER_SUFFIXES = {".tif", ".tiff"}
_BUILDING_KEYS = {"building", "buildings", "building_footprints"}
_ROAD_KEYS = {"road", "roads", "road_network"}
_POPULATION_KEYS = {"population", "population_grid", "worldpop"}


def _require_geopandas():
    try:
        import geopandas as gpd
    except ImportError as error:  # pragma: no cover - exercised without the GIS extra
        raise RuntimeError(
            "处理矢量基础图层需要 GIS 可选依赖；请安装项目的 .[gis] 依赖"
        ) from error
    return gpd


def _require_rasterio():
    try:
        import rasterio
    except ImportError as error:  # pragma: no cover - exercised without the GIS extra
        raise RuntimeError(
            "处理栅格基础图层需要 GIS 可选依赖；请安装项目的 .[gis] 依赖"
        ) from error
    return rasterio


def _safe_layer_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()).strip("_")
    if not cleaned:
        raise ValueError(f"图层名称不能转换为安全文件名: {name!r}")
    return cleaned


def _resolve_existing(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"基础图层不存在或不是文件: {path}")
    return resolved


def _load_area(area: StudyArea):
    """读取研究区文件或 WKT，并返回带原始 CRS 的单要素 GeoDataFrame。"""
    gpd = _require_geopandas()
    boundary_path = Path(area.boundary).expanduser()
    if boundary_path.is_file():
        frame = gpd.read_file(boundary_path)
    else:
        try:
            from shapely import wkt

            geometry = wkt.loads(area.boundary)
        except Exception as error:
            raise FileNotFoundError(
                "StudyArea.boundary 必须是可读取的矢量文件或有效 WKT"
            ) from error
        frame = gpd.GeoDataFrame({"study_area_id": [area.identifier]}, geometry=[geometry], crs=area.coordinate_reference_system)
    if frame.empty or frame.geometry.is_empty.all():
        raise ValueError("研究区边界为空")
    if frame.crs is None:
        frame = frame.set_crs(area.coordinate_reference_system)
    elif str(frame.crs) != area.coordinate_reference_system:
        frame = frame.to_crs(area.coordinate_reference_system)
    merged = frame.geometry.union_all() if hasattr(frame.geometry, "union_all") else frame.geometry.unary_union
    return gpd.GeoDataFrame({"study_area_id": [area.identifier]}, geometry=[merged], crs=frame.crs)


def _clip_vector(source_path: Path, area_frame, target_crs: str, output_path: Path, layer_name: str) -> None:
    gpd = _require_geopandas()
    frame = gpd.read_file(source_path)
    if frame.crs is None:
        raise ValueError(f"矢量图层缺少 CRS: {source_path}")
    frame = frame.to_crs(target_crs)
    area_target = area_frame.to_crs(target_crs)
    mask = area_target.geometry.iloc[0]
    intersects = frame.geometry.notna() & ~frame.geometry.is_empty & frame.geometry.intersects(mask)
    frame = frame.loc[intersects].copy()
    if not frame.empty:
        source_types = frame.geometry.geom_type.copy()
        frame.geometry = frame.geometry.intersection(mask)
        frame = frame.loc[~frame.geometry.is_empty & frame.geometry.notna()].copy()
        # 边界处线与面可能仅接触于一个点；不能把它写成道路/建筑。
        expected = source_types.loc[frame.index].map(
            lambda kind: {"LineString", "MultiLineString"} if "Line" in kind else
            {"Polygon", "MultiPolygon"} if "Polygon" in kind else {kind}
        )
        frame = frame.loc[[kind in allowed for kind, allowed in zip(frame.geometry.geom_type, expected)]].copy()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(output_path, layer=layer_name, driver="GPKG", index=False)


def _clip_raster(source_path: Path, area_frame, target_crs: str, output_path: Path) -> None:
    rasterio = _require_rasterio()
    from rasterio.mask import mask
    from rasterio.warp import Resampling, calculate_default_transform, reproject

    with rasterio.open(source_path) as source:
        if source.crs is None:
            raise ValueError(f"栅格图层缺少 CRS: {source_path}")
        area_source = area_frame.to_crs(source.crs)
        shape = area_source.geometry.iloc[0].__geo_interface__
        try:
            data, clipped_transform = mask(source, [shape], crop=True, filled=False)
        except ValueError as error:
            raise ValueError(f"栅格图层与研究区不相交: {source_path}") from error
        clipped_bounds = rasterio.transform.array_bounds(data.shape[1], data.shape[2], clipped_transform)
        transform, width, height = calculate_default_transform(
            source.crs,
            target_crs,
            data.shape[2],
            data.shape[1],
            *clipped_bounds,
        )
        profile = source.profile.copy()
        nodata = source.nodata
        if nodata is None:
            import numpy as np

            if np.issubdtype(data.dtype, np.floating):
                nodata = float("nan")
            else:
                raise ValueError(f"整数栅格缺少 nodata，无法安全重投影: {source_path}")
        data = data.filled(nodata)
        profile.update(
            driver="GTiff",
            crs=target_crs,
            transform=transform,
            width=width,
            height=height,
            count=data.shape[0],
            compress="deflate",
            nodata=nodata,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(output_path, "w", **profile) as destination:
            for band_index in range(data.shape[0]):
                reproject(
                    source=data[band_index],
                    destination=rasterio.band(destination, band_index + 1),
                    src_transform=clipped_transform,
                    src_crs=source.crs,
                    dst_transform=transform,
                    dst_crs=target_crs,
                    src_nodata=nodata,
                    dst_nodata=nodata,
                    resampling=Resampling.nearest,
                )


def _write_contract(value: Any, path: Path) -> None:
    path.write_text(
        json.dumps(to_payload(value), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def prepare_context_layers(
    area: StudyArea,
    sources: ContextSources,
    target_crs: str,
    output_dir: Path,
) -> ContextLayers:
    """裁切并统一基础图层，同时写出可追溯的 v2 清单。

    矢量输入写为 GeoPackage，GeoTIFF 输入保持为 GeoTIFF。函数不会下载数据，
    也不会为缺失图层生成占位文件。
    """
    validate_contract(area)
    validate_contract(sources)
    if not target_crs.strip():
        raise ValueError("target_crs 不能为空")
    if not sources.event_id.strip():
        raise ValueError("ContextSources.event_id 不能为空")

    output_dir = output_dir.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    area_frame = _load_area(area)
    outputs: dict[str, Path] = {}
    output_names: set[str] = set()

    for layer_key, record in sorted(sources.layers.items()):
        if not layer_key.strip():
            raise ValueError("ContextSources 图层键不能为空")
        if not record.source.strip() or not record.license_id.strip():
            raise ValueError(f"图层 {layer_key} 缺少来源或许可")
        source_path = _resolve_existing(record.path)
        safe_name = _safe_layer_name(layer_key)
        if safe_name.casefold() in output_names:
            raise ValueError(f"图层名称转换后冲突: {layer_key}")
        output_names.add(safe_name.casefold())

        suffix = source_path.suffix.lower()
        if suffix in _VECTOR_SUFFIXES:
            output_path = output_dir / f"{safe_name}.gpkg"
            _clip_vector(source_path, area_frame, target_crs, output_path, safe_name)
        elif suffix in _RASTER_SUFFIXES:
            output_path = output_dir / f"{safe_name}.tif"
            _clip_raster(source_path, area_frame, target_crs, output_path)
        else:
            raise ValueError(
                f"不支持的基础图层格式 {suffix or '<无扩展名>'}: {source_path}"
            )
        outputs[layer_key] = output_path

    result = ContextLayers(
        event_id=sources.event_id,
        study_area_id=area.identifier,
        target_crs=target_crs,
        layers=outputs,
        sources=sources,
    )
    validate_contract(result)
    _write_contract(sources, output_dir / "context_sources.json")
    _write_contract(result, output_dir / "context_layers.json")
    return result


def _check(
    name: str,
    status: QualityStatus,
    expected: Any,
    actual: Any,
    message: str,
) -> CheckItem:
    return CheckItem(name=name, status=status, expected=expected, actual=actual, message=message)


def _overall_status(checks: Iterable[CheckItem]) -> QualityStatus:
    statuses = {item.status for item in checks}
    if "fail" in statuses:
        return "fail"
    if "warning" in statuses:
        return "warning"
    return "pass"


def _layer_group_present(keys: set[str], aliases: set[str]) -> bool:
    return bool({key.casefold() for key in keys} & aliases)


def _vector_context_checks(layer_key: str, path: Path, record: SourceRecord, area_frame, target_crs: str):
    gpd = _require_geopandas()
    checks: list[CheckItem] = []
    metrics: dict[str, Any] = {}
    frame = gpd.read_file(path)
    crs_matches = frame.crs is not None and frame.crs == gpd.GeoSeries([], crs=target_crs).crs
    checks.append(_check(f"{layer_key}.crs", "pass" if crs_matches else "fail", target_crs, str(frame.crs), "图层 CRS 与目标一致" if crs_matches else "图层 CRS 与目标不一致或缺失"))
    invalid_count = int((frame.geometry.isna() | frame.geometry.is_empty | ~frame.geometry.is_valid).sum()) if not frame.empty else 0
    checks.append(_check(f"{layer_key}.geometry", "pass" if invalid_count == 0 else "fail", 0, invalid_count, "几何有效" if invalid_count == 0 else "存在空或无效几何"))
    if record.id_field is not None:
        if record.id_field not in frame.columns:
            checks.append(_check(f"{layer_key}.id_field", "fail", record.id_field, list(frame.columns), "对象 ID 字段不存在"))
        else:
            values = frame[record.id_field]
            invalid_ids = int(values.isna().sum() + values.astype(str).str.strip().eq("").sum())
            duplicate_ids = int(values.dropna().astype(str).duplicated().sum())
            ok = invalid_ids == 0 and duplicate_ids == 0
            checks.append(_check(f"{layer_key}.object_ids", "pass" if ok else "fail", {"invalid": 0, "duplicates": 0}, {"invalid": invalid_ids, "duplicates": duplicate_ids}, "对象 ID 完整且唯一" if ok else "对象 ID 存在空值或重复"))
    elif layer_key.casefold() in (_BUILDING_KEYS | _ROAD_KEYS):
        checks.append(_check(f"{layer_key}.id_field", "fail", "非空 ID 字段", None, "建筑或道路图层必须声明 id_field"))

    if frame.empty:
        coverage_ratio = 0.0
    else:
        area_target = area_frame.to_crs(target_crs)
        study_geometry = area_target.geometry.iloc[0]
        union = frame.geometry.union_all() if hasattr(frame.geometry, "union_all") else frame.geometry.unary_union
        if study_geometry.area > 0 and union.geom_type in {"Polygon", "MultiPolygon"}:
            coverage_ratio = float(union.intersection(study_geometry).area / study_geometry.area)
        else:
            coverage_ratio = 1.0 if union.intersects(study_geometry) else 0.0
    metrics[f"{layer_key}.feature_count"] = int(len(frame))
    metrics[f"{layer_key}.coverage_ratio"] = coverage_ratio
    checks.append(_check(f"{layer_key}.coverage", "pass" if coverage_ratio > 0 else "fail", "> 0", coverage_ratio, "图层与研究区相交" if coverage_ratio > 0 else "图层未覆盖研究区"))
    return checks, metrics


def _raster_context_checks(layer_key: str, path: Path, area_frame, target_crs: str):
    rasterio = _require_rasterio()
    checks: list[CheckItem] = []
    metrics: dict[str, Any] = {}
    with rasterio.open(path) as dataset:
        crs_matches = dataset.crs is not None and dataset.crs.to_string() == target_crs
        checks.append(_check(f"{layer_key}.crs", "pass" if crs_matches else "fail", target_crs, str(dataset.crs), "图层 CRS 与目标一致" if crs_matches else "图层 CRS 与目标不一致或缺失"))
        bounds_geometry = None
        try:
            from shapely.geometry import box

            bounds_geometry = box(*dataset.bounds)
        except ImportError:  # pragma: no cover
            pass
        area_target = area_frame.to_crs(dataset.crs)
        intersects = bool(bounds_geometry and bounds_geometry.intersects(area_target.geometry.iloc[0]))
        checks.append(_check(f"{layer_key}.coverage", "pass" if intersects else "fail", True, intersects, "栅格与研究区相交" if intersects else "栅格未覆盖研究区"))
        metrics[f"{layer_key}.width"] = dataset.width
        metrics[f"{layer_key}.height"] = dataset.height
        metrics[f"{layer_key}.band_count"] = dataset.count
    return checks, metrics


def validate_context_layers(layers: ContextLayers, area: StudyArea) -> ContextQAReport:
    """检查阶段一基础图层的事件、来源、许可、CRS、覆盖和对象 ID。"""
    checks: list[CheckItem] = []
    metrics: dict[str, Any] = {"layer_count": len(layers.layers)}
    warnings: list[str] = []

    checks.append(_check("event_id", "pass" if layers.event_id == layers.sources.event_id else "fail", layers.event_id, layers.sources.event_id, "图层与来源清单事件一致" if layers.event_id == layers.sources.event_id else "图层与来源清单事件不一致"))
    checks.append(_check("study_area_id", "pass" if layers.study_area_id == area.identifier else "fail", area.identifier, layers.study_area_id, "研究区一致" if layers.study_area_id == area.identifier else "研究区不一致"))
    layer_keys = set(layers.layers)
    checks.append(_check("building_layer", "pass" if _layer_group_present(layer_keys, _BUILDING_KEYS) else "fail", "建筑图层", sorted(layer_keys), "存在阶段一必需建筑图层" if _layer_group_present(layer_keys, _BUILDING_KEYS) else "缺少阶段一必需建筑图层"))
    checks.append(_check("road_layer", "pass" if _layer_group_present(layer_keys, _ROAD_KEYS) else "fail", "道路图层", sorted(layer_keys), "存在阶段一必需道路图层" if _layer_group_present(layer_keys, _ROAD_KEYS) else "缺少阶段一必需道路图层"))
    if not _layer_group_present(layer_keys, _POPULATION_KEYS):
        warnings.append("缺少人口图层；允许继续阶段一，但人口暴露统计必须标为未知")
        checks.append(_check("population_layer", "warning", "人口图层或缺失说明", None, warnings[-1]))
    else:
        checks.append(_check("population_layer", "pass", "人口图层", "present", "人口图层已提供"))

    area_frame = _load_area(area)
    for layer_key, output_path in sorted(layers.layers.items()):
        record = layers.sources.layers.get(layer_key)
        if record is None:
            checks.append(_check(f"{layer_key}.source_record", "fail", "SourceRecord", None, "输出图层缺少来源记录"))
            continue
        source_ok = bool(record.source.strip() and record.license_id.strip())
        checks.append(_check(f"{layer_key}.provenance", "pass" if source_ok else "fail", "来源和许可非空", {"source": record.source, "license_id": record.license_id}, "来源与许可完整" if source_ok else "来源或许可缺失"))
        if record.date is None:
            message = f"{layer_key} 缺少数据日期；交接时须说明时效性限制"
            warnings.append(message)
            checks.append(_check(f"{layer_key}.date", "warning", "带时区日期", None, message))
        else:
            checks.append(_check(f"{layer_key}.date", "pass", "带时区日期", record.date.isoformat(), "数据日期已记录"))
        path = output_path.expanduser().resolve()
        if not path.is_file():
            checks.append(_check(f"{layer_key}.file", "fail", "存在且可读", str(path), "输出文件不存在"))
            continue
        checks.append(_check(f"{layer_key}.file", "pass", "存在且可读", str(path), "输出文件存在"))
        try:
            if path.suffix.lower() in _VECTOR_SUFFIXES:
                layer_checks, layer_metrics = _vector_context_checks(layer_key, path, record, area_frame, layers.target_crs)
            elif path.suffix.lower() in _RASTER_SUFFIXES:
                layer_checks, layer_metrics = _raster_context_checks(layer_key, path, area_frame, layers.target_crs)
            else:
                raise ValueError(f"不支持的输出格式: {path.suffix}")
        except Exception as error:
            checks.append(_check(f"{layer_key}.read", "fail", "可读取的 GIS 图层", type(error).__name__, str(error)))
        else:
            checks.extend(layer_checks)
            metrics.update(layer_metrics)

    manifest_path = next(iter(layers.layers.values())).parent / "context_layers.json" if layers.layers else None
    report = ContextQAReport(
        status=_overall_status(checks),
        checks=tuple(checks),
        metrics=metrics,
        warnings=tuple(warnings),
        artifacts={"context_layers": manifest_path} if manifest_path is not None and manifest_path.is_file() else {},
    )
    validate_contract(report)
    return report


def _line_parts(geometry) -> list[Any]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry]
    if geometry.geom_type == "MultiLineString":
        return list(geometry.geoms)
    return []


def _network_topology(geometries: Iterable[Any], tolerance: float) -> dict[str, int]:
    """按端点容差构建轻量拓扑指标，不产生阶段三 RoadGraph。"""
    coordinates: list[tuple[float, float]] = []
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    parent: list[int] = []
    degree: list[int] = []
    self_loops = 0
    segment_count = 0

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    def node_for(point: tuple[float, float]) -> int:
        if tolerance == 0:
            key = (hash(point), 0)
            candidates = buckets.get(key, [])
            for index in candidates:
                if coordinates[index] == point:
                    return index
        else:
            cell = (math.floor(point[0] / tolerance), math.floor(point[1] / tolerance))
            candidates = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    candidates.extend(buckets.get((cell[0] + dx, cell[1] + dy), []))
            for index in candidates:
                existing = coordinates[index]
                if math.hypot(existing[0] - point[0], existing[1] - point[1]) <= tolerance:
                    return index
            key = cell
        index = len(coordinates)
        coordinates.append(point)
        parent.append(index)
        degree.append(0)
        buckets[key].append(index)
        return index

    for geometry in geometries:
        for part in _line_parts(geometry):
            coords = list(part.coords)
            if len(coords) < 2:
                continue
            start = node_for((float(coords[0][0]), float(coords[0][1])))
            end = node_for((float(coords[-1][0]), float(coords[-1][1])))
            segment_count += 1
            if start == end:
                self_loops += 1
                degree[start] += 2
            else:
                degree[start] += 1
                degree[end] += 1
                union(start, end)

    components = len({find(index) for index in range(len(coordinates))}) if coordinates else 0
    return {
        "node_count": len(coordinates),
        "segment_count": segment_count,
        "component_count": components,
        "dangling_node_count": sum(value == 1 for value in degree),
        "self_loop_count": self_loops,
    }


def validate_network(roads_path: Path, spec: NetworkSpec) -> NetworkReport:
    """检查道路 ID、CRS、方向、速度、几何和端点拓扑。"""
    validate_contract(spec)
    checks: list[CheckItem] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}
    artifacts = {"roads": roads_path}

    if spec.snap_tolerance_m < 0:
        checks.append(_check("snap_tolerance_m", "fail", ">= 0", spec.snap_tolerance_m, "捕捉容差不能为负"))
    else:
        checks.append(_check("snap_tolerance_m", "pass", ">= 0", spec.snap_tolerance_m, "捕捉容差合法"))
    if spec.default_speed_kmh <= 0:
        checks.append(_check("default_speed_kmh", "fail", "> 0", spec.default_speed_kmh, "默认速度必须为正"))
    else:
        checks.append(_check("default_speed_kmh", "pass", "> 0", spec.default_speed_kmh, "默认速度合法"))

    try:
        path = _resolve_existing(roads_path)
        gpd = _require_geopandas()
        frame = gpd.read_file(path)
    except Exception as error:
        checks.append(_check("roads_file", "fail", "存在且可读取", str(roads_path), str(error)))
        return NetworkReport(status="fail", checks=tuple(checks), metrics=metrics, warnings=tuple(warnings), artifacts=artifacts)

    metrics["edge_count"] = int(len(frame))
    crs_matches = frame.crs is not None and frame.crs == gpd.GeoSeries([], crs=spec.crs).crs
    checks.append(_check("crs", "pass" if crs_matches else "fail", spec.crs, str(frame.crs), "道路 CRS 与 NetworkSpec 一致" if crs_matches else "道路 CRS 与 NetworkSpec 不一致或缺失"))
    if frame.crs is not None and getattr(frame.crs, "is_geographic", False):
        checks.append(_check("metric_crs", "fail", "投影坐标系（米）", str(frame.crs), "snap_tolerance_m 不能在经纬度坐标中解释"))
    else:
        checks.append(_check("metric_crs", "pass" if frame.crs is not None else "fail", "投影坐标系（米）", str(frame.crs), "道路使用投影坐标系" if frame.crs is not None else "道路缺少 CRS"))

    if spec.edge_id_field not in frame.columns:
        checks.append(_check("edge_id_field", "fail", spec.edge_id_field, list(frame.columns), "道路 ID 字段不存在"))
    else:
        ids = frame[spec.edge_id_field]
        blank = ids.isna() | ids.astype(str).str.strip().eq("")
        duplicates = ids.loc[~blank].astype(str).duplicated(keep=False)
        invalid_count, duplicate_count = int(blank.sum()), int(duplicates.sum())
        metrics.update(invalid_edge_id_count=invalid_count, duplicate_edge_id_count=duplicate_count)
        ok = invalid_count == 0 and duplicate_count == 0
        checks.append(_check("edge_ids", "pass" if ok else "fail", {"blank": 0, "duplicate_rows": 0}, {"blank": invalid_count, "duplicate_rows": duplicate_count}, "道路 ID 完整且唯一" if ok else "道路 ID 存在空值或重复"))

    invalid_geometry = frame.geometry.isna() | frame.geometry.is_empty | ~frame.geometry.is_valid
    wrong_type = ~frame.geometry.geom_type.isin(["LineString", "MultiLineString"])
    invalid_geometry_count = int((invalid_geometry | wrong_type).sum())
    multipart_count = int(frame.geometry.geom_type.eq("MultiLineString").sum())
    metrics.update(invalid_geometry_count=invalid_geometry_count, multipart_edge_count=multipart_count)
    checks.append(_check("line_geometry", "pass" if invalid_geometry_count == 0 else "fail", 0, invalid_geometry_count, "道路几何均为有效线" if invalid_geometry_count == 0 else "存在空、无效或非线几何"))
    if multipart_count:
        message = "存在 MultiLineString 道路；阶段三建图前应按连续路段拆分并保留稳定 edge_id"
        warnings.append(message)
        checks.append(_check("multipart_edges", "warning", 0, multipart_count, message))

    if spec.direction_field is not None:
        if spec.direction_field not in frame.columns:
            checks.append(_check("direction_field", "fail", spec.direction_field, list(frame.columns), "方向字段不存在"))
        else:
            observed = {str(value) for value in frame[spec.direction_field].dropna().unique()}
            metrics["one_way_edge_count"] = int(frame[spec.direction_field].astype(str).isin(spec.one_way_values).sum())
            checks.append(_check("direction_field", "pass", "字段存在", sorted(observed), "方向字段可读取；one_way_values 只用于识别单向值"))
    else:
        checks.append(_check("direction_field", "pass", None, None, "未配置方向字段，所有道路按双向处理"))

    if spec.speed_field is not None:
        if spec.speed_field not in frame.columns:
            checks.append(_check("speed_field", "fail", spec.speed_field, list(frame.columns), "速度字段不存在"))
        else:
            import pandas as pd

            speeds = pd.to_numeric(frame[spec.speed_field], errors="coerce")
            invalid_speed = int((speeds.isna() | (speeds <= 0)).sum())
            metrics["defaulted_speed_count"] = invalid_speed
            if invalid_speed:
                message = f"{invalid_speed} 条道路速度缺失或非正，将使用 default_speed_kmh={spec.default_speed_kmh}"
                warnings.append(message)
                checks.append(_check("speed_values", "warning", "> 0", invalid_speed, message))
            else:
                checks.append(_check("speed_values", "pass", "> 0", 0, "速度值均为正数"))
    else:
        warnings.append("未配置速度字段；全部道路使用默认速度")
        checks.append(_check("speed_field", "warning", "速度字段或默认值", spec.default_speed_kmh, warnings[-1]))

    if spec.blocked_field is not None:
        checks.append(_check("blocked_field", "pass" if spec.blocked_field in frame.columns else "fail", spec.blocked_field, list(frame.columns), "阻断字段存在" if spec.blocked_field in frame.columns else "配置的阻断字段不存在"))

    valid_geometries = frame.loc[~(invalid_geometry | wrong_type)].geometry
    topology = _network_topology(valid_geometries, max(spec.snap_tolerance_m, 0.0))
    metrics.update(topology)
    if topology["segment_count"] == 0:
        checks.append(_check("topology", "fail", "> 0 个有效路段", topology, "没有可用于拓扑检查的道路"))
    elif topology["component_count"] > 1:
        message = f"道路网络包含 {topology['component_count']} 个连通分量；请核对断裂、研究区边界和孤立道路"
        warnings.append(message)
        checks.append(_check("connectivity", "warning", 1, topology["component_count"], message))
    else:
        checks.append(_check("connectivity", "pass", 1, topology["component_count"], "道路端点在给定容差下连通"))
    checks.append(_check("self_loops", "warning" if topology["self_loop_count"] else "pass", 0, topology["self_loop_count"], "存在端点捕捉后形成的自环" if topology["self_loop_count"] else "未发现自环"))

    report = NetworkReport(
        status=_overall_status(checks),
        checks=tuple(checks),
        metrics=metrics,
        warnings=tuple(warnings),
        artifacts=artifacts,
    )
    validate_contract(report)
    return report
