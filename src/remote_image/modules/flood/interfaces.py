"""R2 洪水提取、暴露统计和人工核查接口。"""

from collections.abc import Sequence
from pathlib import Path

from remote_image.core.contracts import (
    ContextLayers, ExposureReport, FloodContext, FloodOptions, FloodRequest,
    FloodResult, PreparedInputs, RasterAsset, ReviewQAReport, ReviewResult,
    ReviewSpec, ReviewTemplate, SpatialQAReport, ThresholdReport,
)


def evaluate_flood_thresholds(inputs: PreparedInputs, candidates: Sequence[FloodOptions], reference: Path | None, output_dir: Path) -> ThresholdReport:
    raise NotImplementedError("R2: 比较候选阈值；无真值时只给定性选择依据")


def run_flood_baseline(request: FloodRequest) -> FloodResult:
    raise NotImplementedError("R2: 使用灾后阈值和灾前非水筛查生成洪水结果")


def polygonize_mask(mask_path: Path, ctx: FloodContext, output_path: Path) -> Path:
    raise NotImplementedError("R2: 将洪水掩膜转换为带事件和方法属性的矢量面")


def summarize_exposure(flood: FloodResult, layers: ContextLayers, area_crs: str) -> ExposureReport:
    raise NotImplementedError("R2: 统计受影响建筑、人口和道路")


def check_damage_geography(result, buildings: Path, tile_index: Path, area_crs: str) -> SpatialQAReport:
    raise NotImplementedError("R2: 检查逐建筑结果、ID、空间偏移和切片边缘")


def create_review_layer(ortho: RasterAsset, buildings: Path, roads: Path | None, spec: ReviewSpec, output_path: Path) -> ReviewTemplate:
    raise NotImplementedError("R2: 分层抽取有限建筑和道路，生成空白核查模板")


def ingest_review(review_file: Path, event_id: str, reviewer_id: str) -> ReviewResult:
    raise NotImplementedError("R2: 导入人工填写结果，不把模板当成结论")


def qa_review(review: ReviewResult, ortho: RasterAsset, buildings: Path, roads: Path | None, snap_tolerance_m: float) -> ReviewQAReport:
    raise NotImplementedError("R2: 检查核查位置、证据、有效期和冲突")


def join_uav_review(buildings: Path, roads: Path | None, review: ReviewResult, snap_tolerance_m: float, output_dir: Path) -> ReviewResult:
    raise NotImplementedError("R2: 关联对象并输出 review_layer 与 road_state_updates")
