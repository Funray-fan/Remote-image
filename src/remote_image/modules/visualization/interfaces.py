"""C3 地图与查询接口；只展示标准结果，不重新计算科学指标。"""

from collections.abc import Sequence
from pathlib import Path

from remote_image.core.contracts import (
    DamageResult, DecisionResult, ExposureReport, FeatureDetail, LayerId,
    LayerManifest, MapHandle, MapLayer, PriorityResult, RasterAsset,
    ReviewResult, RouteResult, StudyArea,
)


def load_layers(manifest: LayerManifest) -> Sequence[MapLayer]:
    raise NotImplementedError("C3: 严格按清单加载图层")


def render_map(layers: Sequence[MapLayer], area: StudyArea, display_crs: str, max_raster_side_px: int, offline_basemap: Path | None = None) -> MapHandle:
    raise NotImplementedError("C3: 创建可缩放的离线地图视图")


def render_summary(data: Sequence[ExposureReport] | DecisionResult, handle: MapHandle) -> None:
    raise NotImplementedError("C3: 显示已计算统计、缺失数据和不确定性")


def query_feature(event_id: str, layer_id: str, feature_id: str) -> FeatureDetail:
    raise NotImplementedError("C3: 按事件、图层和对象ID查询")


def render_damage_layer(event_id: str, result: DamageResult, handle: MapHandle, confidence_display_threshold: float) -> LayerId:
    raise NotImplementedError("C3: 按类别和置信度显示逐建筑结果")


def show_building_detail(event_id: str, layer_id: str, building_id: str) -> FeatureDetail:
    raise NotImplementedError("C3: 显示建筑损毁类别、置信度和模型版本")


def render_orthomosaic(asset: RasterAsset, handle: MapHandle) -> LayerId:
    raise NotImplementedError("C3: 显示重点区正射")


def render_review_layer(result: ReviewResult, handle: MapHandle) -> LayerId:
    raise NotImplementedError("C3: 区分已核查、未知、过期和未核查对象")


def render_routes(result: DecisionResult | RouteResult, handle: MapHandle) -> LayerId:
    raise NotImplementedError("C3: 显示路线、成本、状态和不可达目标")


def render_priority_areas(result: DecisionResult | PriorityResult, handle: MapHandle) -> LayerId:
    raise NotImplementedError("C3: 显示重点区得分组成和数据覆盖率")
