"""Read C1/C2 building damage results for the C3 map."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .stage1 import (
    MapLayer,
    VisualizationInputError,
    _coordinates,
    _read_json,
    _read_vector_collection,
)


# Order also controls the legend and the counts table.
DAMAGE_CLASSES = {
    "no-damage": ("未损毁", "#15803d"),
    "minor-damage": ("轻度损毁", "#b45309"),
    "major-damage": ("重度损毁", "#ea580c"),
    "destroyed": ("完全损毁", "#b91c1c"),
    "un-classified": ("未分类", "#64748b"),
}
DAMAGE_LAYER_ID = "stage2-damage"


@dataclass(frozen=True)
class DamageMapResult:
    event_id: str
    model_name: str
    model_version: str
    vector_path: Path
    features: dict[str, dict[str, Any]]
    input_asset_ids: tuple[str, ...]
    warnings: tuple[str, ...]
    synthetic: bool


@dataclass
class DamageMapHandle:
    event_id: str
    layers: list[MapLayer] = field(default_factory=list)
    buildings: dict[str, dict[str, Any]] = field(default_factory=dict)


def _local_file(value: Any, base: Path, root: Path) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise VisualizationInputError("结果文件路径不能为空")
    path = (base / value).resolve()
    if not path.is_relative_to(root):
        raise VisualizationInputError("阶段二文件路径必须位于仓库内")
    if not path.is_file():
        raise VisualizationInputError(f"阶段二文件不存在：{path}")
    return path


def _text(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise VisualizationInputError(f"阶段二字段 {key} 必须是非空字符串")
    return value


def _confidence(value: Any) -> bool:
    return type(value) in (int, float) and 0 <= value <= 1


def load_damage_result(
    path: Path, *, allowed_root: Path, spatial_qa_path: Path | None = None
) -> DamageMapResult:
    """Load a standard DamageResult; require R2 QA for non-fixture results."""
    root = allowed_root.resolve()
    path = _local_file(path, root, root)
    data = _read_json(path)
    meta, artifacts = data.get("meta"), data.get("artifacts")
    if (
        data.get("schema_version") != "1.0"
        or not isinstance(meta, dict)
        or meta.get("schema_version") != "1.0"
        or not isinstance(artifacts, dict)
    ):
        raise VisualizationInputError("需要 schema_version 1.0 的 DamageResult")
    event_id = _text(meta, "event_id")
    model_name = _text(data, "model_name")
    model_version = _text(data, "model_version")
    if meta.get("method") != "building_damage" or "damage_vector" not in artifacts:
        raise VisualizationInputError("阶段二需要逐建筑 damage_vector，分割掩膜不能用于建筑查询")
    asset_ids, warnings = meta.get("input_asset_ids"), meta.get("warnings")
    if (
        not isinstance(asset_ids, list) or not asset_ids
        or not all(isinstance(item, str) and item for item in asset_ids)
        or not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings)
    ):
        raise VisualizationInputError("DamageResult 的输入资产或告警字段无效")
    vector = _local_file(artifacts["damage_vector"], path.parent, root)
    _local_file(artifacts.get("tile_index"), path.parent, root)
    metadata = _read_json(_local_file(artifacts.get("metadata"), path.parent, root))
    parameters = meta.get("parameters")
    synthetic = metadata.get("fixture_only") is True or (
        isinstance(parameters, dict) and parameters.get("fixture_only") is True
    )
    if not synthetic:
        qa = _read_json(_local_file(
            spatial_qa_path or (path.parent / "spatial_qa.json"), root, root
        ))
        if qa.get("status") != "pass":
            raise VisualizationInputError("空间质检状态须为 pass，当前结果不能正式展示")
        if qa.get("event_id", event_id) != event_id:
            raise VisualizationInputError("空间质检与损毁结果的事件 ID 不一致")
        qa_warnings = qa.get("warnings", [])
        if isinstance(qa_warnings, list):
            warnings = [*warnings, *(item for item in qa_warnings if isinstance(item, str))]

    collection = _read_vector_collection(vector)
    if vector.suffix.lower() != ".gpkg" and collection.get("crs") is not None:
        crs = collection["crs"]
        props = crs.get("properties") if isinstance(crs, dict) else None
        name = props.get("name") if isinstance(props, dict) else None
        if name not in {"EPSG:4326", "OGC:CRS84", "urn:ogc:def:crs:OGC:1.3:CRS84"}:
            raise VisualizationInputError("damage_vector GeoJSON 必须使用 WGS 84 经纬度")
    features: dict[str, dict[str, Any]] = {}
    for feature in collection["features"]:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise VisualizationInputError("damage_vector 含有无效要素")
        properties, geometry = feature.get("properties"), feature.get("geometry")
        if not isinstance(properties, dict):
            raise VisualizationInputError("建筑要素缺少属性")
        building_id = _text(properties, "building_id")
        if building_id in features:
            raise VisualizationInputError(f"重复建筑 ID：{building_id}")
        if (properties.get("event_id"), properties.get("model_name"), properties.get("model_version")) != (
            event_id, model_name, model_version
        ):
            raise VisualizationInputError(f"建筑 {building_id} 的事件或模型版本与结果不一致")
        _text(properties, "source")
        damage_class = _text(properties, "damage_class")
        if damage_class not in DAMAGE_CLASSES or not _confidence(properties.get("confidence")):
            raise VisualizationInputError(f"建筑 {building_id} 的损毁类别或置信度不符合当前 v1 schema")
        if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise VisualizationInputError(f"建筑 {building_id} 需要面几何")
        points = list(_coordinates(geometry))
        if not points or not all(-180 <= x <= 180 and -90 <= y <= 90 for x, y in points):
            raise VisualizationInputError(f"建筑 {building_id} 的坐标无效或不是经纬度")
        features[building_id] = feature
    return DamageMapResult(
        event_id, model_name, model_version, vector, features, tuple(asset_ids), tuple(warnings), synthetic
    )


def render_damage_layer(
    event_id: str,
    result: DamageMapResult,
    handle: DamageMapHandle,
    confidence_display_threshold: float = 0.0,
) -> str:
    """Add or replace the damage display layer without changing the result."""
    if event_id != result.event_id or event_id != handle.event_id:
        raise VisualizationInputError("只能叠加同一事件的图层")
    if not _confidence(confidence_display_threshold):
        raise VisualizationInputError("显示阈值必须在 0 到 1 之间")
    handle.buildings = {
        building_id: feature for building_id, feature in result.features.items()
        if feature["properties"]["confidence"] >= confidence_display_threshold
    }
    handle.layers[:] = [layer for layer in handle.layers if layer.id != DAMAGE_LAYER_ID]
    handle.layers.append(MapLayer(
        id=DAMAGE_LAYER_ID, title="建筑损毁", kind="vector", path=result.vector_path,
        crs="EPSG:4326", source=f"{result.model_name} · {result.model_version}",
        palette={key: color for key, (_, color) in DAMAGE_CLASSES.items()},
        color_property="damage_class",
    ))
    return DAMAGE_LAYER_ID


def show_building_detail(
    event_id: str, layer_id: str, building_id: str, handle: DamageMapHandle
) -> dict[str, Any] | None:
    """Look up a visible building by the three identifiers."""
    if event_id != handle.event_id or layer_id != DAMAGE_LAYER_ID:
        return None
    feature = handle.buildings.get(building_id)
    return dict(feature["properties"]) if feature else None


def damage_counts(features: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts = Counter(feature["properties"]["damage_class"] for feature in features.values())
    return {key: counts[key] for key in DAMAGE_CLASSES}
