"""C3 stage-one offline map application.

Run from the repository root with ``streamlit run app/main.py`` after
installing the project UI and GIS extras.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import streamlit as st

from remote_image.modules.visualization.stage1 import (
    VisualizationInputError,
    feature_ids,
    load_manifest,
    load_summary,
    query_feature,
    render_map,
    render_summary,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "tests" / "fixtures" / "stage1_synthetic" / "layer_manifest.json"


def _safe_path(value: str, root: Path) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise VisualizationInputError("为避免误读仓库外文件，manifest 和图层路径必须位于数据目录内")
    return resolved


def main() -> None:
    st.set_page_config(page_title="Remote Image | 洪水影响地图", layout="wide")
    st.title("洪水影响评估地图")
    st.caption("阶段一 · C3 可视化 · 支持本地数据离线展示")

    with st.sidebar:
        st.header("案例数据")
        manifest_value = st.text_input(
            "layer_manifest.json 路径（相对仓库根目录）",
            value=str(DEFAULT_MANIFEST.relative_to(REPOSITORY_ROOT)),
        )
        try:
            manifest_path = _safe_path(manifest_value, REPOSITORY_ROOT)
            manifest = load_manifest(manifest_path, allowed_root=REPOSITORY_ROOT)
            layers = manifest["layers"]
        except (OSError, json.JSONDecodeError, VisualizationInputError) as exc:
            st.error(str(exc))
            st.stop()

        event_id = str(manifest.get("event_id", "unknown"))
        st.caption(f"事件：{event_id}")
        st.caption("合成样例" if manifest.get("synthetic") else "数据来源以 manifest 为准")

        st.subheader("图层")
        enabled_ids = []
        for layer in layers:
            if st.checkbox(layer.title, value=layer.visible, key=f"layer-{layer.id}"):
                enabled_ids.append(layer.id)
            details = " · ".join(value for value in (layer.time, layer.crs, layer.source) if value)
            if details:
                st.caption(details)

        st.subheader("图例")
        for layer in layers:
            if layer.id not in enabled_ids:
                continue
            entries = layer.palette.items() if layer.palette else [(layer.title, layer.color or "#087e8b")]
            for label, color in entries:
                if str(color).lower() in {"transparent", "none"}:
                    continue
                if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(color)):
                    st.warning(f"图层 {layer.title} 的图例颜色格式无效")
                    continue
                st.markdown(
                    f'<span style="display:inline-block;width:12px;height:12px;background:{color};margin-right:8px"></span>{html.escape(layer.title)}: {html.escape(str(label))}',
                    unsafe_allow_html=True,
                )

    map_col, summary_col = st.columns([2.1, 1])
    with map_col:
        st.subheader("地图")
        try:
            markup = render_map(layers, enabled_ids)
            st.html(markup)
        except VisualizationInputError as exc:
            st.error(str(exc))

    with summary_col:
        st.subheader("统计摘要")
        summary_path = manifest.get("summary_path")
        if not summary_path:
            st.info("manifest 未指定统计摘要文件")
        else:
            try:
                summary = render_summary(load_summary(summary_path))
                labels = {
                    "flood_area_m2": "洪水面积（m²）",
                    "affected_buildings": "受影响建筑数",
                    "affected_population": "受影响人口",
                }
                for name, value in summary["statistics"].items():
                    st.metric(labels.get(name, name), value)
                for warning in summary["warnings"]:
                    st.warning(str(warning))
                if summary["metadata"]:
                    st.caption("运行信息")
                    st.json(summary["metadata"])
            except (OSError, VisualizationInputError) as exc:
                st.error(str(exc))

        st.subheader("要素查询")
        query_layers = [layer for layer in layers if layer.kind == "vector" and layer.id in enabled_ids]
        if not query_layers:
            st.info("打开一个矢量图层后即可查询其要素。")
        else:
            selected_layer = st.selectbox("矢量图层", query_layers, format_func=lambda layer: layer.title)
            try:
                ids = feature_ids(selected_layer.path)
                if not ids:
                    st.info("该图层没有要素")
                else:
                    selected_id = st.selectbox("要素 ID", ids)
                    feature = query_feature(selected_layer.path, selected_id)
                    if feature is not None:
                        st.json(feature.get("properties") or {})
            except VisualizationInputError as exc:
                st.error(str(exc))


if __name__ == "__main__":
    main()
