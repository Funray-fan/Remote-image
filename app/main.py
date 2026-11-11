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
import streamlit.components.v1 as components

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


@st.cache_data(show_spinner=False)
def cached_map(layers, enabled_ids, versions):
    return render_map(layers, enabled_ids)


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
    st.caption("阶段一 · 灾前灾后对照、候选水体与暴露统计 · 本地离线地图")

    with st.sidebar:
        st.header("案例数据")
        cases = {"合成功能样例": DEFAULT_MANIFEST}
        completed = sorted(REPOSITORY_ROOT.glob('outputs/*/stage1/integrated/*/layer_manifest.json'), reverse=True)
        for path in completed:
            status = path.parent / 'run_status.json'
            if status.is_file() and json.loads(status.read_text(encoding='utf-8')).get('status') == 'complete':
                cases[f"涿州洪水 · {path.parent.name}"] = path
        if "pending_case" in st.session_state:
            st.session_state['case'] = st.session_state.pop('pending_case')
        default_index = None if 'case' in st.session_state else (1 if len(cases)>1 else 0)
        choice = st.selectbox("选择案例", list(cases), index=default_index, key="case")
        if choice is None:
            st.info("请选择一个案例。")
            st.stop()
        if st.button("运行涿州阶段一分析", type="primary"):
            try:
                from remote_image.workflows.integrated import run_case
                with st.spinner("正在核对输入、分析候选水体并生成统计与地图，请稍候…"):
                    output = run_case(REPOSITORY_ROOT/'configs/integrated-zhuozhou.json')
                st.session_state['pending_case'] = f"涿州洪水 · {output.name}"
                st.rerun()
            except Exception as exc:
                st.error(f"运行失败：{exc}。请检查本地案例输入是否准备齐全。")
        with st.expander("自定义结果文件"):
            manifest_value = st.text_input(
                "图层清单路径（相对项目目录）",
                value=str(cases[choice].relative_to(REPOSITORY_ROOT)),
                key=f"manifest-{choice}",
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
        is_synthetic = manifest.get("synthetic") or choice == "合成功能样例"
        st.caption("合成样例 · 仅验证功能" if is_synthetic else "历史案例 · 水体候选，识别精度尚未验证")

        st.subheader("图层")
        enabled_ids = []
        for layer in layers:
            if st.checkbox(layer.title, value=layer.visible, key=f"layer-{layer.id}"):
                enabled_ids.append(layer.id)
            details = " · ".join(value for value in (layer.time, layer.crs, layer.source) if value)
            if details:
                with st.expander(f"{layer.title} · 来源"):
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
            with st.spinner("正在加载地图…"):
                markup = cached_map(layers, enabled_ids, tuple((str(l.path),l.path.stat().st_mtime_ns) for l in layers))
            components.html(markup, height=800, scrolling=True)
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
                    "candidate_area_m2": "新增水体候选面积（m²）",
                    "building_objects_intersecting": "交叠建筑来源对象数",
                    "road_overlap_length_m": "道路交叠长度（m）",
                    "population_exposed": "人口暴露（未知）",
                }
                for name, value in summary["statistics"].items():
                    if name in labels:
                        st.metric(labels[name], "未知" if value is None else f"{value:,.2f}" if isinstance(value,float) else value)
                if is_synthetic:
                    for warning in summary["warnings"]:
                        st.warning(str(warning))
                else:
                    st.warning("候选交叠不等于建筑损毁或道路阻断；人口与识别精度未验证。")
                    with st.expander("数据来源与适用限制"):
                        for warning in summary["warnings"]:
                            st.write(str(warning))
                st.download_button("下载运行摘要", json.dumps(load_summary(summary_path),ensure_ascii=False,indent=2),
                                   file_name="summary.json", mime="application/json")
                if summary["metadata"]:
                    with st.expander("运行信息"):
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
