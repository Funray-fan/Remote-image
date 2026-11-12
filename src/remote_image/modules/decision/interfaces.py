"""R3 基础图层、路网、路线和重点区接口。"""

from datetime import datetime
from pathlib import Path

from remote_image.core.contracts import (
    ContextLayers, ContextQAReport, ContextSources, DecisionRequest,
    NetworkReport, NetworkSpec, PriorityResult, ReviewResult, RoadGraph,
    RoadStateUpdateResult, RouteResult, StudyArea,
)
from remote_image.modules.decision.stage1 import (
    prepare_context_layers as _prepare_context_layers,
    validate_context_layers as _validate_context_layers,
    validate_network as _validate_network,
)


def prepare_context_layers(area: StudyArea, sources: ContextSources, target_crs: str, output_dir: Path) -> ContextLayers:
    return _prepare_context_layers(area, sources, target_crs, output_dir)


def validate_context_layers(layers: ContextLayers, area: StudyArea) -> ContextQAReport:
    return _validate_context_layers(layers, area)


def validate_network(roads_path: Path, spec: NetworkSpec) -> NetworkReport:
    return _validate_network(roads_path, spec)


def build_road_graph(roads_path: Path, spec: NetworkSpec) -> RoadGraph:
    raise NotImplementedError("R3: 生成可跨进程交接的节点和边文件")


def update_road_states(base_states: Path, review: ReviewResult, as_of: datetime, output_path: Path) -> RoadStateUpdateResult:
    raise NotImplementedError("R3: 使用有证据且有效的核查记录更新道路状态")


def plan_routes(request: DecisionRequest) -> RouteResult:
    raise NotImplementedError("R3: 排除确认阻断边并按未知策略计算候选路线")


def rank_priority_areas(request: DecisionRequest, routes: RouteResult) -> PriorityResult:
    raise NotImplementedError("R3: 在固定1km格网上汇总损毁、人口与可达性")
