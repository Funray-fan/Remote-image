"""Display R3 context evidence without computing or replacing R2 damage QA."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .stage1 import MapLayer, VisualizationInputError, _read_json
from .stage2 import _local_file, _validate_v2


@dataclass(frozen=True)
class ContextView:
    layers: tuple[MapLayer, ...]
    sources: tuple[dict[str, Any], ...]
    report: dict[str, Any] | None
    notices: tuple[str, ...]


def load_context_view(
    path: Path, *, event_id: str, allowed_root: Path,
    qa_path: Path | None = None, study_area_id: str | None = None,
) -> ContextView:
    root = allowed_root.resolve()
    path = _local_file(path, root, root)
    data = _read_json(path)
    _validate_v2("ContextLayers", data)
    if data["event_id"] != event_id or data["sources"]["event_id"] != event_id:
        raise VisualizationInputError("R3 背景图层与当前损毁结果的事件不一致，不能跨事件叠加")
    if study_area_id is not None and data["study_area_id"] != study_area_id:
        raise VisualizationInputError("R3 背景图层与损毁结果的研究区不一致")
    records = data["sources"]["layers"]
    if set(records) != set(data["layers"]):
        raise VisualizationInputError("R3 图层与来源记录不一一对应")
    layers, sources = [], []
    for key, raw in data["layers"].items():
        source = records[key]
        file = _local_file(raw, path.parent, root)
        if _local_file(source["path"], path.parent, root) != file:
            raise VisualizationInputError(f"R3 {key} 来源路径与图层不一致")
        suffix = file.suffix.lower()
        if suffix not in {".geojson", ".json", ".gpkg", ".tif", ".tiff"}:
            raise VisualizationInputError(f"R3 不支持显示的图层格式：{suffix}")
        layers.append(MapLayer(
            id=f"context:{key}", title=f"背景 · {key}",
            kind="raster" if suffix in {".tif", ".tiff"} else "vector",
            path=file, crs=data["target_crs"], source=source["source"],
            time=source["date"], visible=False,
        ))
        sources.append({"图层": key, "来源": source["source"], "许可": source["license_id"],
                        "观测日期": source["date"] or "未知", "对象 ID 字段": source["id_field"] or "未提供"})
    report_path = qa_path or path.parent / "context_qa.json"
    if qa_path is None and not report_path.is_file():
        return ContextView((), tuple(sources), None, ("尚未提供 R3 复核报告，背景图层暂不叠加。",))
    report_path = _local_file(report_path, root, root)
    report = _read_json(report_path)
    _validate_v2("ContextQAReport", report)
    # ContextQAReport has no event_id: bind it to the selected manifest explicitly.
    artifact = report["artifacts"].get("context_layers")
    if artifact is None or _local_file(artifact, report_path.parent, root) != path:
        raise VisualizationInputError("R3 报告未关联当前 context_layers，无法确认报告所属事件")
    for name in ("event_id", "sources.event_id"):
        checks = [item for item in report["checks"] if item["name"] == name]
        if not checks or any(item["status"] != "pass" or item["actual"] != event_id
                             or item["expected"] != event_id for item in checks):
            raise VisualizationInputError("R3 报告的事件检查与当前事件不一致")
    notices = list(report["warnings"])
    notices.append("R3 背景复核不能替代 R2 灾损空间质检；相交检查不代表完整覆盖或灾时数据准确。")
    if not any(item["name"].endswith(".coverage") for item in report["checks"]):
        notices.append("当前事件覆盖未验证：报告未提供研究区相交检查。")
    if any(source["观测日期"] == "未知" for source in sources):
        notices.append("部分背景图层观测日期未知，时相一致性未确认。")
    if report["status"] == "fail" or any(item["status"] == "fail" for item in report["checks"]):
        notices.append("R3 复核失败，背景图层暂不叠加。")
        layers = []
    return ContextView(tuple(layers), tuple(sources), report, tuple(dict.fromkeys(notices)))
