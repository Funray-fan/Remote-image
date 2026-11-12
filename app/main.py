"""C3 offline map application.

Run from the repository root with ``streamlit run app/main.py`` after
installing the project UI and GIS extras.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import replace
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
from remote_image.modules.visualization.stage2 import (
    DAMAGE_CLASSES,
    DamageMapHandle,
    damage_counts,
    load_damage_result,
    render_damage_layer,
    show_building_detail,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "tests" / "fixtures" / "stage1_synthetic" / "layer_manifest.json"
STAGE2_FIXTURE = DEFAULT_MANIFEST.parent.parent / "stage2_synthetic"


@st.cache_data(show_spinner=False)
def cached_map(layers, enabled_ids, versions):
    return render_map(layers, enabled_ids, interactive=True)


def _safe_path(value: str, root: Path) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise VisualizationInputError("为避免误读仓库外文件，manifest 和图层路径必须位于数据目录内")
    return resolved


def _show_map(markup: str) -> None:
    """Keep scripts and raster images inside a map frame with explicit height."""
    if hasattr(st, "iframe"):
        st.iframe(markup, height=740, alt="可交互的灾情地图")
    else:
        from streamlit.components.v1 import html as map_frame

        map_frame(markup, height=740, scrolling=True)


def show_stage1() -> None:
    st.title("洪水影响评估地图")
    st.caption("阶段一 · 灾前灾后对照、候选水体与暴露统计 · 本地离线地图")

    with st.sidebar:
        st.header("案例数据")
        cases = {"合成功能样例": DEFAULT_MANIFEST}
        completed = sorted(REPOSITORY_ROOT.glob('outputs/*/stage1/integrated/*/layer_manifest.json'), reverse=True)
        for path in completed:
            status = path.parent / 'run_status.json'
            if status.is_file() and json.loads(status.read_text(encoding='utf-8')).get('status') == 'complete':
                summary_file = path.parent / "summary.json"
                summary = load_summary(summary_file) if summary_file.is_file() else {}
                label = "合成联调" if summary.get("synthetic") else str(summary.get("event_id", "历史案例"))
                if label == "zhuozhou_2023_flood":
                    label = "涿州洪水"
                cases[f"{label} · {path.parent.name}"] = path
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
        is_synthetic = manifest.get("synthetic", False)
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
                markup = cached_map(
                    layers, enabled_ids,
                    tuple((str(layer.path), layer.path.stat().st_mtime_ns) for layer in layers),
                )
            _show_map(markup)
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


def show_stage2() -> None:
    st.title("建筑灾损评估地图")
    st.caption("阶段二 · 光学遥感逐建筑结果 · 离线展示")
    with st.sidebar:
        st.header("阶段二数据")
        sample = st.radio("数据来源", ["合成演示", "本地推理结果"]) == "合成演示"
        if sample:
            result_path = STAGE2_FIXTURE / "damage_result.json"
            optics = str((STAGE2_FIXTURE / "layer_manifest.json").relative_to(REPOSITORY_ROOT))
            flood = str(DEFAULT_MANIFEST.relative_to(REPOSITORY_ROOT))
            qa_path = None
        else:
            st.caption("路径相对于仓库根目录。先由上游完成模型推理和空间质检。")
            value = st.text_input("逐建筑结果 DamageResult 路径", placeholder="outputs/事件/stage2/damage_result.json")
            qa = st.text_input("空间质检路径", placeholder="默认读取结果同目录的 spatial_qa.json")
            optics = st.text_input("光学影像清单路径（可选）", placeholder="outputs/事件/stage2/layer_manifest.json")
            flood = st.text_input("洪水图层清单路径（可选）", placeholder="outputs/事件/stage1/layer_manifest.json")
            if not value.strip():
                st.info("输入逐建筑结果路径后即可查看建筑损毁。")
                return
            try:
                result_path = _safe_path(value.strip(), REPOSITORY_ROOT)
                qa_path = _safe_path(qa.strip(), REPOSITORY_ROOT) if qa.strip() else None
            except (OSError, VisualizationInputError) as exc:
                st.error(str(exc))
                return

        try:
            result = load_damage_result(result_path, allowed_root=REPOSITORY_ROOT, spatial_qa_path=qa_path)
        except (OSError, VisualizationInputError) as exc:
            st.error(str(exc))
            return

        st.caption(f"事件：{result.event_id}")
        threshold = st.slider("地图显示置信度下限", 0.0, 1.0, 0.0, 0.01)
        st.caption("此阈值只筛选展示和查询，原始预测保持不变。未知置信度仅在阈值为 0 时显示。")
        handle = DamageMapHandle(result.event_id)
        context_notes = []
        has_optical_raster = False
        for prefix, name, value in (("optical", "光学影像", optics), ("flood", "洪水", flood)):
            if not value.strip():
                continue
            try:
                path = _safe_path(value.strip(), REPOSITORY_ROOT)
                context = load_manifest(path, allowed_root=REPOSITORY_ROOT)
                if context["event_id"] != result.event_id:
                    view = "可在阶段一单独查看该洪水案例。" if prefix == "flood" else ""
                    context_notes.append(
                        f"{name}清单属于事件 {context['event_id']}，与当前事件 {result.event_id} 不同，未叠加。{view}"
                    )
                    continue
                if bool(context.get("synthetic")) != result.synthetic:
                    context_notes.append(f"{name}与损毁结果的数据性质不同，合成数据和真实数据分别展示。")
                    continue
                for layer in context["layers"]:
                    # Give optical imagery priority over the SAR basemap in a combined view.
                    visible = layer.visible
                    if prefix == "flood" and has_optical_raster and layer.kind == "raster" and not layer.palette:
                        visible = False
                    handle.layers.append(replace(
                        layer, id=f"{prefix}:{layer.id}", title=f"{name} · {layer.title}", visible=visible,
                    ))
                if prefix == "optical":
                    has_optical_raster = any(layer.kind == "raster" and layer.visible for layer in context["layers"])
            except (OSError, VisualizationInputError) as exc:
                context_notes.append(f"无法加载{name}清单：{exc}")

        damage_id = render_damage_layer(result.event_id, result, handle, threshold)
        st.subheader("图层")
        enabled = [
            layer.id for layer in handle.layers
            if st.checkbox(layer.title, value=layer.visible, key=f"s2:{result_path}:{layer.id}")
        ]
        st.subheader("损毁等级图例")
        for label, color in DAMAGE_CLASSES.values():
            st.markdown(
                f'<span style="color:{color};font-size:1.2em">■</span> {label}', unsafe_allow_html=True,
            )

    if result.synthetic:
        st.warning("合成演示：影像、建筑位置、损毁标签及置信度均用于验证界面，不代表真实灾情或模型精度。")
    for note in context_notes:
        st.info(note)
    for warning in result.warnings:
        st.warning(warning)

    map_col, detail_col = st.columns([2, 1])
    with map_col:
        st.subheader("地图")
        try:
            markup = render_map(
                handle.layers, enabled,
                vector_features={damage_id: handle.buildings.values()}, interactive=True,
            )
            _show_map(markup)
        except VisualizationInputError as exc:
            st.error(str(exc))
    with detail_col:
        st.subheader("结果摘要")
        st.text(f"事件：{result.event_id}\n模型：{result.model_name}\n模型版本：{result.model_version}")
        st.caption("输入资产：" + "、".join(result.input_asset_ids))
        total, shown = st.columns(2)
        total.metric("建筑总数", len(result.features))
        shown.metric("当前显示", len(handle.buildings) if damage_id in enabled else 0)
        counts = damage_counts(result.features)
        shown_counts = damage_counts(handle.buildings if damage_id in enabled else {})
        st.table([
            {"损毁等级": label, "全部": counts[code], "显示": shown_counts[code]}
            for code, (label, _) in DAMAGE_CLASSES.items()
        ])
        st.subheader("建筑详情")
        if damage_id not in enabled:
            st.info("打开建筑损毁图层后即可查询。")
        elif not handle.buildings:
            st.info("没有符合当前阈值的建筑。")
        else:
            building_id = st.selectbox(
                "建筑 ID（可搜索）", sorted(handle.buildings), index=None,
                key=f"s2-building:{result_path}",
            )
            if building_id is not None:
                detail = show_building_detail(result.event_id, damage_id, building_id, handle)
                if detail is not None:
                    st.text(
                        f"损毁等级：{DAMAGE_CLASSES[detail['damage_class']][0]}\n"
                        f"原始置信度：{detail['confidence'] if detail['confidence'] is not None else '未知'}\n"
                        f"来源：{detail.get('source') or '输入资产 ' + '、'.join(result.input_asset_ids)}\n"
                        f"模型版本：{detail['model_version']}"
                    )
                    if detail.get("reason"):
                        st.caption(f"判定说明：{detail['reason']}")
                    with st.expander("查看原始属性"):
                        st.json(detail)


def main() -> None:
    st.set_page_config(page_title="Remote Image | 遥感灾情地图", layout="wide")
    stage = st.sidebar.radio("工作阶段", ["阶段一 · 洪水影响", "阶段二 · 建筑灾损"])
    if stage.startswith("阶段二"):
        show_stage2()
    else:
        show_stage1()


if __name__ == "__main__":
    main()
