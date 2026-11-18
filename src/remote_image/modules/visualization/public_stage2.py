"""C3 public-contract adapter; map state is owned by the caller's handle."""

from dataclasses import dataclass, field, replace
from pathlib import Path
from uuid import uuid4
from weakref import WeakValueDictionary

from remote_image.core.contracts import DamageResult, FeatureDetail, MapHandle
from remote_image.core.serialization import to_payload
from .stage1 import VisualizationInputError
from .stage2 import DamageMapHandle, _load_damage_payload, render_damage_layer as _render


@dataclass(frozen=True)
class C3MapHandle(MapHandle):
    state: DamageMapHandle = field(compare=False)
    allowed_root: Path = field(compare=False)
    base_dir: Path = field(compare=False)
    spatial_qa_path: Path | None = field(default=None, compare=False)


_maps: WeakValueDictionary[str, C3MapHandle] = WeakValueDictionary()


def create_damage_map_handle(
    event_id: str, *, allowed_root: Path, base_dir: Path | None = None,
    spatial_qa_path: Path | None = None,
) -> C3MapHandle:
    """Keep this handle alive while displaying/querying its layer; no global event state."""
    root = allowed_root.resolve()
    base = (base_dir or root).resolve()
    if not event_id.strip() or not base.is_relative_to(root):
        raise VisualizationInputError("地图需要事件 ID 和仓库内的结果目录")
    return C3MapHandle(uuid4().hex, DamageMapHandle(event_id), root, base, spatial_qa_path)


def render_damage_layer(event_id: str, result: DamageResult, handle: MapHandle,
                        confidence_display_threshold: float) -> str:
    if not isinstance(handle, C3MapHandle):
        raise VisualizationInputError("请使用 create_damage_map_handle 创建 C3 地图句柄")
    view = _load_damage_payload(to_payload(result), base=handle.base_dir,
                                root=handle.allowed_root, spatial_qa_path=handle.spatial_qa_path)
    public_id = f"{handle.map_id}:stage2-damage"
    candidate = DamageMapHandle(handle.state.event_id,
        [layer for layer in handle.state.layers if layer.id != public_id])
    layer = _render(event_id, view, candidate, confidence_display_threshold)
    # Unique per map: concurrent maps of the same event cannot overwrite each other's queries.
    handle.state.layers[:] = [replace(item, id=public_id) if item.id == layer else item
                             for item in candidate.layers]
    handle.state.buildings = candidate.buildings
    _maps[public_id] = handle
    return public_id


def show_building_detail(event_id: str, layer_id: str, building_id: str) -> FeatureDetail:
    handle = _maps.get(layer_id)
    if handle is None or handle.state.event_id != event_id:
        raise VisualizationInputError("地图图层不存在或事件不一致")
    feature = handle.state.buildings.get(building_id)
    if feature is None:
        raise VisualizationInputError("建筑不存在或已被显示阈值过滤")
    from copy import deepcopy
    return FeatureDetail(event_id, layer_id, building_id,
                         deepcopy(feature["properties"]), deepcopy(feature["geometry"]))
