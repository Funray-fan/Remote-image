"""Offline map rendering helpers for the C3 stage-one interface.

This is a visualization adapter, not a replacement for C1's public contracts.
It consumes a small layer manifest that points at standard GeoJSON and
GeoTIFF artifacts. The manifest can later be produced from FloodResult and
the project's approved LayerManifest contract.
"""

from __future__ import annotations

import base64
import html
import json
import math
import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


class VisualizationInputError(ValueError):
    """Raised when an input cannot be shown safely and consistently."""


@dataclass(frozen=True)
class MapLayer:
    id: str
    title: str
    kind: str
    path: Path
    visible: bool = True
    crs: str | None = None
    source: str = "unknown"
    color: str | None = None
    time: str | None = None
    palette: Mapping[str, str] | None = None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise VisualizationInputError(f"找不到输入文件：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VisualizationInputError(f"无法读取 JSON 文件：{path} ({exc})") from exc
    if not isinstance(payload, dict):
        raise VisualizationInputError(f"JSON 顶层必须是对象：{path}")
    return payload


def load_layers(manifest_path: str | Path) -> list[MapLayer]:
    """Read a C3 layer manifest and verify each referenced artifact exists."""
    manifest_path = Path(manifest_path).resolve()
    data = _read_json(manifest_path)
    if not isinstance(data.get("layers"), list) or not data["layers"]:
        raise VisualizationInputError("layer_manifest.layers 必须是非空数组")

    layers: list[MapLayer] = []
    ids: set[str] = set()
    for index, item in enumerate(data["layers"]):
        if not isinstance(item, dict):
            raise VisualizationInputError(f"第 {index + 1} 个图层配置必须是对象")
        missing = {"id", "title", "kind", "path"} - item.keys()
        if missing:
            raise VisualizationInputError(
                f"第 {index + 1} 个图层缺少字段：{', '.join(sorted(missing))}"
            )
        if not all(isinstance(item[key], str) and item[key].strip() for key in ("id", "title", "kind", "path")):
            raise VisualizationInputError(f"第 {index + 1} 个图层的 id/title/kind/path 必须是非空字符串")
        layer_id = item["id"].strip()
        if layer_id in ids:
            raise VisualizationInputError(f"图层 id 重复：{layer_id}")
        ids.add(layer_id)
        kind = str(item["kind"]).lower()
        if kind not in {"vector", "raster"}:
            raise VisualizationInputError(f"不支持的图层类型：{kind}")
        artifact = (manifest_path.parent / str(item["path"])).resolve()
        if artifact.suffix.lower() not in {".geojson", ".json", ".gpkg", ".tif", ".tiff"}:
            raise VisualizationInputError(f"不支持的图层文件格式：{artifact.suffix or '(无扩展名)'}")
        if kind == "vector" and artifact.suffix.lower() in {".geojson", ".json"} and not item.get("crs"):
            raise VisualizationInputError(f"矢量图层 {layer_id} 必须声明 CRS")
        if not artifact.is_file():
            raise VisualizationInputError(f"图层文件不存在：{artifact}")
        palette = item.get("palette")
        if palette is not None and not isinstance(palette, dict):
            raise VisualizationInputError(f"图层 {layer_id} 的 palette 必须是对象")
        color = item.get("color")
        if color is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", str(color)):
            raise VisualizationInputError(f"图层 {layer_id} 的 color 必须是 #RRGGBB 格式")
        layers.append(
            MapLayer(
                id=layer_id,
                title=str(item["title"]),
                kind=kind,
                path=artifact,
                visible=bool(item.get("visible", True)),
                crs=item.get("crs"),
                source=str(item.get("source", "unknown")),
                color=color,
                time=item.get("time"),
                palette=palette,
            )
        )
    return layers


def load_manifest(
    manifest_path: str | Path, *, allowed_root: str | Path | None = None
) -> dict[str, Any]:
    """Load the descriptive fields in a C3 manifest alongside its layers."""
    path = Path(manifest_path).resolve()
    data = _read_json(path)
    if not data.get("event_id"):
        raise VisualizationInputError("layer_manifest.event_id 不能为空")
    if not isinstance(data.get("layers"), list) or not data["layers"]:
        raise VisualizationInputError("layer_manifest.layers 必须是非空数组")
    if allowed_root is not None:
        root = Path(allowed_root).resolve()
        for item in data.get("layers", []):
            if not isinstance(item, dict) or "path" not in item:
                continue
            layer_path = (path.parent / str(item["path"])).resolve()
            if not layer_path.is_relative_to(root):
                raise VisualizationInputError("图层路径必须位于允许的数据目录内")
    data["layers"] = load_layers(path)
    summary_path = data.get("summary")
    if summary_path:
        if not isinstance(summary_path, str):
            raise VisualizationInputError("layer_manifest.summary 必须是相对路径字符串")
        resolved = (path.parent / str(summary_path)).resolve()
        if allowed_root is not None and not resolved.is_relative_to(Path(allowed_root).resolve()):
            raise VisualizationInputError("统计摘要路径必须位于允许的数据目录内")
        if not resolved.is_file():
            raise VisualizationInputError(f"统计摘要文件不存在：{resolved}")
        data["summary_path"] = resolved
    return data


def load_summary(summary_path: str | Path) -> dict[str, Any]:
    """Load a display summary without recalculating upstream statistics."""
    data = _read_json(Path(summary_path))
    if not data.get("event_id"):
        raise VisualizationInputError("summary.event_id 不能为空")
    statistics = data.get("statistics", {})
    warnings = data.get("warnings", [])
    if not isinstance(statistics, dict):
        raise VisualizationInputError("summary.statistics 必须是对象")
    if not isinstance(warnings, list):
        raise VisualizationInputError("summary.warnings 必须是数组")
    return data


def render_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize upstream summary fields for display; do not recalculate them."""
    return {
        "event_id": summary.get("event_id", "unknown"),
        "statistics": dict(summary.get("statistics", {})),
        "warnings": list(summary.get("warnings", [])),
        "metadata": {
            key: summary[key]
            for key in ("method", "method_version", "created_at", "source")
            if key in summary
        },
    }


def query_feature(vector_path: str | Path, feature_id: str) -> dict[str, Any] | None:
    """Find a GeoJSON feature using ``feature_id`` or the GeoJSON ``id``."""
    data = _read_vector_collection(Path(vector_path))
    features = data.get("features")
    if not isinstance(features, list):
        raise VisualizationInputError("GeoJSON.features 必须是数组")
    for feature in features:
        if not isinstance(feature, dict):
            raise VisualizationInputError("GeoJSON.features 中的每一项都必须是对象")
        properties = feature.get("properties") or {}
        candidate = properties.get("feature_id", feature.get("id"))
        if candidate is not None and str(candidate) == str(feature_id):
            return feature
    return None


def feature_ids(vector_path: str | Path) -> list[str]:
    """Return stable query IDs from a GeoJSON FeatureCollection."""
    data = _read_vector_collection(Path(vector_path))
    if any(not isinstance(feature, dict) for feature in data["features"]):
        raise VisualizationInputError("GeoJSON.features 中的每一项都必须是对象")
    result: list[str] = []
    for index, feature in enumerate(data["features"]):
        properties = feature.get("properties") or {}
        identifier = _identifier(properties, feature, index)
        result.append(str(identifier))
    return result


def _identifier(properties: Mapping[str, Any], feature: Mapping[str, Any], fallback: int) -> Any:
    for key in ("feature_id", "building_id", "edge_id", "id"):
        if properties.get(key) is not None:
            return properties[key]
    return feature.get("id", fallback)


def _read_vector_collection(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in {".geojson", ".json"}:
        data = _read_json(path)
    elif path.suffix.lower() == ".gpkg":
        try:
            import geopandas as gpd
        except ImportError as exc:
            raise VisualizationInputError(
                "读取 GeoPackage 需要 GIS 依赖，请安装项目可选依赖：python -m pip install -e '.[gis]'"
            ) from exc
        try:
            frame = gpd.read_file(path)
        except Exception as exc:
            raise VisualizationInputError(f"无法读取 GeoPackage：{path} ({exc})") from exc
        if frame.crs is None:
            raise VisualizationInputError(f"GeoPackage 图层缺少 CRS：{path}")
        try:
            data = json.loads(frame.to_crs("EPSG:4326").to_json(drop_id=True))
        except Exception as exc:
            raise VisualizationInputError(f"无法将 GeoPackage 转为 EPSG:4326：{path} ({exc})") from exc
    else:
        raise VisualizationInputError("矢量图层仅支持 GeoJSON 或 GeoPackage")
    if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        raise VisualizationInputError("查询输入必须是 GeoJSON FeatureCollection")
    return data


def _coordinates(geometry: Mapping[str, Any]) -> Iterable[tuple[float, float]]:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "GeometryCollection":
        for child in geometry.get("geometries", []):
            yield from _coordinates(child)
        return

    def walk(value: Any) -> Iterable[tuple[float, float]]:
        if (
            isinstance(value, (list, tuple))
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            yield float(value[0]), float(value[1])
        elif isinstance(value, (list, tuple)):
            for child in value:
                yield from walk(child)

    yield from walk(coordinates)


def _feature_collection(layer: MapLayer) -> dict[str, Any]:
    data = _read_vector_collection(layer.path)
    if (
        layer.path.suffix.lower() != ".gpkg"
        and layer.crs
        and layer.crs.upper() not in {"EPSG:4326", "OGC:CRS84", "CRS84"}
    ):
        raise VisualizationInputError(
            f"矢量图层 {layer.title} 的 CRS 是 {layer.crs}；当前离线渲染器要求经纬度坐标 EPSG:4326"
        )
    return data


def _raster_payload(layer: MapLayer, max_dimension: int = 512) -> tuple[str, tuple[float, float, float, float]]:
    try:
        import numpy as np
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.warp import transform_bounds
    except ImportError as exc:
        raise VisualizationInputError(
            "渲染 GeoTIFF 需要 GIS 依赖，请安装项目可选依赖：python -m pip install -e '.[gis]'"
        ) from exc

    with rasterio.open(layer.path) as dataset:
        if dataset.crs is None:
            raise VisualizationInputError(f"栅格缺少 CRS：{layer.title}")
        scale = min(1.0, max_dimension / max(dataset.width, dataset.height))
        width = max(1, int(dataset.width * scale))
        height = max(1, int(dataset.height * scale))
        values = dataset.read(
            out_shape=(dataset.count, height, width),
            masked=True,
            resampling=Resampling.average,
        )
        bounds = transform_bounds(dataset.crs, "EPSG:4326", *dataset.bounds, densify_pts=21)

    band_count = values.shape[0]
    if layer.palette:
        raw = np.asarray(values[0].filled(255))
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        for raw_value, color in layer.palette.items():
            try:
                number = int(raw_value)
                color = str(color).lstrip("#")
                if color.lower() in {"transparent", "none"}:
                    rgba[raw == number] = (0, 0, 0, 0)
                    continue
                red, green, blue = (int(color[i : i + 2], 16) for i in (0, 2, 4))
            except (ValueError, IndexError):
                raise VisualizationInputError(f"无效的栅格 palette 项：{raw_value}: {color}")
            selected = raw == number
            rgba[selected] = (red, green, blue, 210)
        rgba[np.ma.getmaskarray(values[0])] = (0, 0, 0, 0)
    else:
        if band_count >= 3:
            channels = [values[i].astype(float).filled(np.nan) for i in range(3)]
        else:
            gray = values[0].astype(float).filled(np.nan)
            channels = [gray, gray, gray]
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        valid = np.isfinite(channels[0])
        for index, channel in enumerate(channels):
            finite = channel[np.isfinite(channel)]
            if finite.size == 0:
                continue
            low, high = np.percentile(finite, (2, 98))
            if high <= low:
                high = low + 1
            rgba[:, :, index] = np.nan_to_num(
                np.clip((channel - low) * 255 / (high - low), 0, 255), nan=0
            ).astype(np.uint8)
        rgba[:, :, 3] = np.where(valid, 230, 0).astype(np.uint8)

    png = _encode_png(rgba)
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii"), tuple(bounds)


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def _encode_png(rgba: Any) -> bytes:
    height, width, _ = rgba.shape
    scanlines = b"".join(b"\x00" + rgba[row].tobytes() for row in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) + _png_chunk(
        b"IDAT", zlib.compress(scanlines, level=6)
    ) + _png_chunk(b"IEND", b"")


def _project(point: tuple[float, float], bounds: tuple[float, float, float, float], width: int, height: int, pad: int) -> tuple[float, float]:
    west, south, east, north = bounds
    lon, lat = point
    latitude_limit = 85.05112878
    south = max(-latitude_limit, min(latitude_limit, south))
    north = max(-latitude_limit, min(latitude_limit, north))
    lat = max(-latitude_limit, min(latitude_limit, lat))
    mercator = lambda value: math.log(math.tan(math.pi / 4 + math.radians(value) / 2))
    y_south, y_north, y = mercator(south), mercator(north), mercator(lat)
    west_x, east_x, longitude_x = math.radians(west), math.radians(east), math.radians(lon)
    dx = max(east_x - west_x, 1e-9)
    dy = max(y_north - y_south, 1e-9)
    scale = min((width - 2 * pad) / dx, (height - 2 * pad) / dy)
    map_width, map_height = dx * scale, dy * scale
    offset_x = (width - map_width) / 2
    offset_y = (height - map_height) / 2
    return (
        offset_x + (longitude_x - west_x) * scale,
        offset_y + (y_north - y) * scale,
    )


def _geometry_svg(geometry: Mapping[str, Any], bounds: tuple[float, float, float, float], width: int, height: int, pad: int, color: str) -> str:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")

    def path_for_ring(ring: list[Any]) -> str:
        points = [_project((float(p[0]), float(p[1])), bounds, width, height, pad) for p in ring]
        if not points:
            return ""
        return "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in points) + " Z"

    if kind == "GeometryCollection":
        return "".join(
            _geometry_svg(child, bounds, width, height, pad, color)
            for child in geometry.get("geometries", [])
        )
    if kind == "Point":
        x, y = _project((float(coordinates[0]), float(coordinates[1])), bounds, width, height, pad)
        return f'<circle cx="{x:.2f}" cy="{y:.2f}" r="7" fill="{html.escape(color)}" stroke="#fff" stroke-width="2" />'
    if kind == "MultiPoint":
        return "".join(
            _geometry_svg({"type": "Point", "coordinates": point}, bounds, width, height, pad, color)
            for point in coordinates
        )
    if kind == "LineString":
        points = [_project((float(p[0]), float(p[1])), bounds, width, height, pad) for p in coordinates]
        joined = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        return f'<polyline points="{joined}" fill="none" stroke="{html.escape(color)}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" />'
    if kind == "MultiLineString":
        return "".join(
            _geometry_svg({"type": "LineString", "coordinates": line}, bounds, width, height, pad, color)
            for line in coordinates
        )
    if kind == "Polygon":
        path = " ".join(path_for_ring(ring) for ring in coordinates)
    elif kind == "MultiPolygon":
        path = " ".join(path_for_ring(ring) for polygon in coordinates for ring in polygon)
    else:
        return ""
    return f'<path d="{path}" fill="{html.escape(color)}" fill-opacity="0.38" stroke="{html.escape(color)}" stroke-width="2" fill-rule="evenodd" />'


def render_map(layers: Iterable[MapLayer], visible_layer_ids: Iterable[str] | None = None) -> str:
    """Render visible local vector/raster assets as a self-contained SVG map."""
    layers = list(layers)
    visible_ids = set(visible_layer_ids) if visible_layer_ids is not None else {
        layer.id for layer in layers if layer.visible
    }
    visible = [layer for layer in layers if layer.id in visible_ids]
    if not visible:
        return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 700" role="img"><rect width="1000" height="700" fill="#edf3f5"/><text x="500" y="350" text-anchor="middle" font-size="22" fill="#53636b">请选择至少一个图层</text></svg>'

    features_by_layer: dict[str, list[dict[str, Any]]] = {}
    bounds_points: list[tuple[float, float]] = []
    raster_data: dict[str, tuple[str, tuple[float, float, float, float]]] = {}
    for layer in visible:
        if layer.kind == "vector":
            collection = _feature_collection(layer)
            layer_features = []
            for feature in collection.get("features", []):
                if not isinstance(feature, dict):
                    continue
                geometry = feature.get("geometry")
                if not isinstance(geometry, dict):
                    continue
                coords = list(_coordinates(geometry))
                if not coords:
                    continue
                bounds_points.extend(coords)
                layer_features.append(feature)
            features_by_layer[layer.id] = layer_features
        elif layer.kind == "raster":
            payload, raster_bounds = _raster_payload(layer)
            raster_data[layer.id] = (payload, raster_bounds)
            west, south, east, north = raster_bounds
            bounds_points.extend([(west, south), (east, north)])

    if not bounds_points:
        return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 700" role="img"><rect width="1000" height="700" fill="#edf3f5"/><text x="500" y="350" text-anchor="middle" font-size="20" fill="#53636b">所选图层没有可显示的空间要素</text></svg>'

    longitudes = [point[0] for point in bounds_points if math.isfinite(point[0])]
    latitudes = [point[1] for point in bounds_points if math.isfinite(point[1])]
    west, east = min(longitudes), max(longitudes)
    south, north = min(latitudes), max(latitudes)
    if east - west < 1e-8:
        west, east = west - 0.001, east + 0.001
    if north - south < 1e-8:
        south, north = south - 0.001, north + 0.001
    dx, dy = east - west, north - south
    west, east = west - dx * 0.06, east + dx * 0.06
    south, north = south - dy * 0.06, north + dy * 0.06
    bounds = (west, south, east, north)

    width, height, pad = 1000, 700, 35
    body: list[str] = []
    for layer in visible:
        if layer.id in raster_data:
            payload, (rwest, rsouth, reast, rnorth) = raster_data[layer.id]
            x1, y1 = _project((rwest, rnorth), bounds, width, height, pad)
            x2, y2 = _project((reast, rsouth), bounds, width, height, pad)
            body.append(
                f'<image href="{payload}" x="{x1:.2f}" y="{y1:.2f}" width="{x2-x1:.2f}" height="{y2-y1:.2f}" preserveAspectRatio="none" />'
            )
        for index, feature in enumerate(features_by_layer.get(layer.id, [])):
            properties = feature.get("properties") or {}
            feature_id = _identifier(properties, feature, f"{layer.id}-{index+1}")
            encoded_properties = html.escape(json.dumps(properties, ensure_ascii=False), quote=True)
            title = html.escape(f"{layer.title} · {feature_id}")
            color = layer.color or "#087e8b"
            shape = _geometry_svg(feature["geometry"], bounds, width, height, pad, color)
            body.append(
                f'<g class="map-feature" tabindex="0" role="button" data-feature-id="{html.escape(str(feature_id), quote=True)}" data-properties="{encoded_properties}" onclick="showFeature(this)" onkeydown="if(event.key===\'Enter\'||event.key===\' \')showFeature(this)"><title>{title}</title>{shape}</g>'
            )

    return (
        '<div style="font-family:Arial,sans-serif;color:#172b32">'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 700" role="img" aria-label="阶段一灾情地图" style="width:100%;height:auto;background:#edf3f5;border:1px solid #d9e2e5;border-radius:8px">'
        '<rect width="1000" height="700" fill="#edf3f5"/>' + "".join(body) +
        '<text x="18" y="680" font-size="13" fill="#53636b">WGS 84 · 离线本地渲染</text></svg>'
        '<div id="feature-info" style="min-height:46px;padding:10px 12px;margin-top:8px;background:#f7fafb;border:1px solid #d9e2e5;border-radius:6px;white-space:pre-wrap">点击地图要素查看属性</div>'
        '<script>function showFeature(el){let p={};try{p=JSON.parse(el.dataset.properties||"{}")}catch(e){};document.getElementById("feature-info").textContent="feature_id: "+el.dataset.featureId+"\\n"+JSON.stringify(p,null,2)}</script>'
        '</div>'
    )
