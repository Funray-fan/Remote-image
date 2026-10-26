"""v1.6 工作流的公共接口，机器契约版本为 2.0。

本文件只定义交接对象和协议，不实现遥感算法。路径在 JSON 中使用项目相对路径，
时间使用带时区 ISO 8601；历史 schemas/v1 只用于读取和验证旧版样例。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol, TypeAlias

SCHEMA_VERSION = "2.0"
JSONValue = Any
AssetStatus = Literal["planned", "verified", "acquired", "usable"]
Stage = Literal["stage1", "stage2", "stage3"]
ResamplingName = Literal["nearest", "bilinear", "cubic", "average", "mode"]
QualityStatus = Literal["pass", "warning", "fail"]
DamageTask = Literal["building_damage", "building_segmentation"]
DamageClass = Literal["no-damage", "minor-damage", "major-damage", "destroyed", "un-classified"]
Polarization = Literal["VV", "VH"]
CostMode = Literal["distance", "time", "risk_weighted"]
RoadStatus = Literal["blocked", "open", "unknown"]
Confirmation = Literal["confirmed", "unconfirmed"]
SplitName = Literal["train", "val", "test"]
ClassMap: TypeAlias = dict[str, DamageClass]
LayerId: TypeAlias = str


def utc_now() -> datetime:
    """为所有默认时间提供一致的 UTC 时区。"""
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class StudyArea:
    identifier: str
    boundary: str
    coordinate_reference_system: str = "EPSG:4326"


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str
    source_url: str | None
    retrieved_at: datetime | None
    license_id: str
    sha256: str | None
    spatial_coverage: str
    time_range: tuple[datetime | None, datetime | None]
    status: AssetStatus
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class RasterAsset:
    asset_id: str
    path: Path
    acquired_at: datetime | None
    source: str
    coordinate_reference_system: str
    pixel_size_m: float | None = None
    bands: tuple[str, ...] = ()
    footprint: Path | None = None
    source_type: Literal["satellite", "uav_orthomosaic", "public_orthomosaic"] = "satellite"
    is_substitute: bool = False
    quality_notes: str | None = None


@dataclass(frozen=True)
class GridSpec:
    """transform 为 GeoTIFF 仿射变换六系数 (a,b,c,d,e,f)。"""
    transform: tuple[float, float, float, float, float, float]
    width: int
    height: int
    pixel_size_x_m: float
    pixel_size_y_m: float


@dataclass(frozen=True)
class PreparedInputs:
    pre_event: RasterAsset | None
    post_event: RasterAsset
    study_area_id: str
    grid: GridSpec
    valid_mask: Path | None


@dataclass(frozen=True)
class ResultMeta:
    schema_version: Literal["2.0"]
    event_id: str
    study_area_id: str
    input_asset_ids: tuple[str, ...]
    method: str
    method_version: str
    parameters: dict[str, JSONValue] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class CheckItem:
    name: str
    status: QualityStatus
    expected: JSONValue
    actual: JSONValue
    message: str


@dataclass(frozen=True, kw_only=True)
class QualityReport:
    status: QualityStatus
    checks: tuple[CheckItem, ...] = ()
    metrics: dict[str, JSONValue] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    artifacts: dict[str, Path] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class RasterValidationReport(QualityReport):
    pass


@dataclass(frozen=True, kw_only=True)
class ValidationReport(QualityReport):
    pass


@dataclass(frozen=True, kw_only=True)
class NetworkReport(QualityReport):
    pass


@dataclass(frozen=True, kw_only=True)
class OrthomosaicQualityReport(QualityReport):
    pass


@dataclass(frozen=True, kw_only=True)
class SpatialQAReport(QualityReport):
    pass


@dataclass(frozen=True, kw_only=True)
class ReviewQAReport(QualityReport):
    pass


@dataclass(frozen=True, kw_only=True)
class ContextQAReport(QualityReport):
    pass


@dataclass(frozen=True)
class DataReadinessItem:
    event_id: str
    stage: Stage
    purpose: str
    source_url: str | None
    license_id: str
    acquired_at: datetime | None
    product_level: str
    bands: tuple[str, ...]
    pixel_size_m: float | None
    labels_available: bool
    download_bytes: int | None
    extracted_bytes: int | None
    storage_path: Path | None
    compute_requirements: str
    owner: str
    checker: str | None
    checked_at: datetime | None
    evidence_uri: str | None
    status: AssetStatus
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaseDataReadiness:
    event_id: str
    items: tuple[DataReadinessItem, ...]
    schema_version: Literal["2.0"] = SCHEMA_VERSION


@dataclass(frozen=True)
class SARPreprocessSpec:
    input_product_type: str
    input_scale: Literal["raw_dn", "sigma0_linear", "sigma0_db"]
    orbit_id: str
    relative_orbit: int | None
    orbit_direction: Literal["ascending", "descending"]
    polarizations: tuple[Polarization, ...]
    target_crs: str
    dem_path: Path | None = None
    speckle_method: Literal["none", "refined_lee"] = "none"
    speckle_window_px: int | None = None


@dataclass(frozen=True)
class SARPreparedAsset:
    asset: RasterAsset
    record: AssetRecord
    report_path: Path
    backscatter_quantity: Literal["sigma0"] = "sigma0"
    value_scale: Literal["db"] = "db"


@dataclass(frozen=True)
class FloodOptions:
    polarizations: tuple[Polarization, ...]
    post_thresholds_db: dict[str, float]
    pre_water_thresholds_db: dict[str, float]
    polarization_rule: Literal["single", "all", "any"]
    permanent_water_mask: Path | None = None
    exclusion_mask: Path | None = None
    min_patch_area_m2: float | None = None
    method: Literal["sar_post_threshold"] = "sar_post_threshold"


@dataclass(frozen=True)
class FloodContext:
    event_id: str
    study_area_id: str
    method: str
    method_version: str
    parameters: dict[str, JSONValue]
    output_crs: str


@dataclass(frozen=True)
class FloodRequest:
    event_id: str
    study_area: StudyArea
    inputs: PreparedInputs
    options: FloodOptions
    output_dir: Path


@dataclass(frozen=True)
class FloodResult:
    artifacts: dict[str, Path]
    meta: ResultMeta


@dataclass(frozen=True, kw_only=True)
class ThresholdReport(QualityReport):
    candidate_options: tuple[FloodOptions, ...]
    selected_options: FloodOptions
    reference_available: bool
    selection_reason: str


@dataclass(frozen=True)
class SourceRecord:
    path: Path
    source: str
    date: datetime | None
    license_id: str
    id_field: str | None


@dataclass(frozen=True)
class ContextSources:
    """携带事件 ID，使 prepare_context_layers 不依赖隐式全局上下文。"""
    event_id: str
    layers: dict[str, SourceRecord]


@dataclass(frozen=True)
class ContextLayers:
    event_id: str
    study_area_id: str
    target_crs: str
    layers: dict[str, Path]
    sources: ContextSources
    created_at: datetime = field(default_factory=utc_now)
    schema_version: Literal["2.0"] = SCHEMA_VERSION


@dataclass(frozen=True)
class ExposureReport:
    meta: ResultMeta
    statistics_path: Path
    affected_features_path: Path | None
    metrics: dict[str, float | int | None]
    units: dict[str, str]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class InferenceOptions:
    tile_size_px: int | None = None
    overlap_ratio: float | None = None
    confidence_threshold: float | None = None
    device: str | None = None
    batch_size: int | None = None


@dataclass(frozen=True)
class InferenceLimits:
    """可覆盖参数的硬限制；None 表示不增加超出基本合法范围的限制。"""
    tile_size_min_px: int = 1
    tile_size_max_px: int | None = None
    allowed_tile_sizes_px: tuple[int, ...] = ()
    overlap_ratio_max: float = 0.99
    confidence_threshold_min: float = 0.0
    confidence_threshold_max: float = 1.0
    allowed_devices: tuple[str, ...] = ("cpu",)
    batch_size_max: int | None = None


@dataclass(frozen=True)
class ModelInputSpec:
    sensors: tuple[str, ...]
    bands: tuple[str, ...]
    pixel_size_min_m: float
    pixel_size_max_m: float
    requires_pre_event: bool
    normalization: dict[str, float]
    tile_size_px: int
    nodata_policy: str


@dataclass(frozen=True)
class TrainingConfig:
    seed: int
    epochs: int
    batch_size: int
    learning_rate: float
    device: str
    train_split: str = "train"
    val_split: str = "val"
    test_split: str = "test"


@dataclass(frozen=True)
class DatasetItem:
    sample_id: str
    event_id: str
    scene_id: str
    image_pair_id: str
    group_id: str
    split: SplitName
    pre_event_path: Path | None
    post_event_path: Path
    label_path: Path
    footprint_path: Path | None
    source: str
    license_id: str


@dataclass(frozen=True)
class DatasetManifest:
    dataset_name: str
    dataset_version: str
    items: tuple[DatasetItem, ...]
    source_url: str
    license_id: str
    split_strategy: Literal["scene_or_image_pair"] = "scene_or_image_pair"
    spatial_overlap_checked: bool = False
    overlap_report_path: Path | None = None
    schema_version: Literal["2.0"] = SCHEMA_VERSION


@dataclass(frozen=True)
class DatasetSplit:
    name: SplitName
    items: tuple[DatasetItem, ...]


@dataclass(frozen=True)
class DatasetBundle:
    manifest: DatasetManifest
    splits: dict[str, DatasetSplit]


@dataclass(frozen=True)
class ModelArtifact:
    model_name: str
    model_version: str
    task: DamageTask
    weights_path: Path
    weights_sha256: str
    training_config: TrainingConfig
    dataset_manifest_path: Path
    trained_at: datetime


@dataclass(frozen=True, kw_only=True)
class EvaluationReport(QualityReport):
    model_name: str
    model_version: str
    dataset_name: str
    dataset_version: str
    split: SplitName
    sample_count: int
    class_counts: dict[str, int]
    seed: int
    split_strategy: Literal["scene_or_image_pair"]
    spatial_overlap_checked: bool
    per_class: dict[str, dict[str, float | None]]
    confusion_matrix: tuple[tuple[int, ...], ...]
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObjectAggregationSpec:
    geometry_source: Literal["request_footprints", "model_localization"]
    id_rule: str
    background_code: int
    damage_class_map: ClassMap
    confidence_definition: Literal["mean_class_probability", "majority_vote_fraction"]
    low_confidence_policy: Literal["un-classified"] = "un-classified"
    tile_merge_rule: str = "mean_probability_over_valid_overlap"
    empty_pixel_policy: Literal["un-classified_null_confidence_with_reason"] = (
        "un-classified_null_confidence_with_reason"
    )


@dataclass(frozen=True)
class ModelManifest:
    model_name: str
    model_version: str
    task: DamageTask
    weights_path: Path
    weights_sha256: str
    input_spec: ModelInputSpec
    inference_defaults: InferenceOptions
    inference_limits: InferenceLimits
    object_aggregation: ObjectAggregationSpec
    class_map: ClassMap
    dependencies: dict[str, str]
    evaluation_path: Path
    schema_version: Literal["2.0"] = SCHEMA_VERSION


@dataclass(frozen=True)
class DamageRequest:
    event_id: str
    study_area: StudyArea
    post_event: RasterAsset
    model_name: str
    model_version: str
    pre_event: RasterAsset | None = None
    building_footprints: Path | None = None
    task: DamageTask = "building_damage"


@dataclass(frozen=True)
class DamageResult:
    artifacts: dict[str, Path]
    model_name: str
    model_version: str
    meta: ResultMeta


@dataclass(frozen=True, kw_only=True)
class ApplicabilityReport(QualityReport):
    """status 表示检查质量，applicability 独立表示能否启用模型。"""
    applicability: Literal["applicable", "not_applicable", "unknown"]
    model_name: str
    model_version: str
    asset_id: str


@dataclass(frozen=True)
class OrthomosaicRequest:
    event_id: str
    study_area: StudyArea
    image_directory: Path
    positioning_source: Literal["GNSS", "RTK", "PPK", "unknown"]
    control_source: Literal["GCP", "none", "unknown"]
    ground_control_points: Path | None
    output_dir: Path


@dataclass(frozen=True)
class ReviewSpec:
    """事件 ID 显式输入，避免从资产文件名猜测事件。"""
    event_id: str
    review_as_of: datetime
    sample_n: int = 180
    road_sample_n: int = 30
    seed: int = 42
    sampling_strategy: Literal["stratified_area"] = "stratified_area"


@dataclass(frozen=True)
class ReviewTemplate:
    event_id: str
    template_path: Path
    sample_ids: tuple[str, ...]
    sample_n: int
    seed: int
    eligible_count: int
    sampling_strategy: Literal["stratified_area"]
    road_sample_ids: tuple[str, ...] = ()
    road_sample_n: int = 0
    road_eligible_count: int = 0


@dataclass(frozen=True)
class ReviewRecord:
    event_id: str
    object_type: Literal["building", "road"]
    object_id: str
    review_status: Literal["pending", "reviewed", "cannot_determine"]
    damage_class: DamageClass | None
    road_status: RoadStatus | None
    confirmation: Confirmation
    source: str
    evidence_uri: str | None
    reviewer_id: str
    reviewed_at: datetime | None
    expires_at: datetime | None
    notes: str


@dataclass(frozen=True)
class ReviewResult:
    artifacts: dict[str, Path]
    meta: ResultMeta


@dataclass(frozen=True)
class NetworkSpec:
    crs: str
    edge_id_field: str
    direction_field: str | None
    speed_field: str | None
    snap_tolerance_m: float
    default_speed_kmh: float
    one_way_values: tuple[str, ...]
    blocked_field: str | None


@dataclass(frozen=True)
class RoadGraph:
    """跨进程交接使用节点/边文件；内存图由 R3 自行加载。"""
    nodes_path: Path
    edges_path: Path
    crs: str
    directed: bool
    node_count: int
    edge_count: int
    spec: NetworkSpec


@dataclass(frozen=True)
class RescuePoint:
    point_id: str
    point_type: Literal["rescue_base", "shelter", "target"]
    geometry: dict[str, JSONValue]
    name: str
    capacity: int | None
    source: str
    updated_at: datetime


@dataclass(frozen=True)
class RoadStateRecord:
    edge_id: str
    status: RoadStatus
    confirmation: Confirmation
    source: str
    observed_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    reviewer_id: str | None
    evidence_uri: str | None
    confidence: float | None
    notes: str


@dataclass(frozen=True)
class RoadStateUpdateResult:
    effective_states_path: Path
    changes_path: Path
    accepted_count: int
    rejected_count: int
    as_of: datetime
    report: QualityReport


@dataclass(frozen=True)
class RouteOptions:
    start_ids: tuple[str, ...]
    goal_ids: tuple[str, ...]
    as_of: datetime
    cost_mode: CostMode = "distance"
    blocked_policy: Literal["exclude"] = "exclude"
    candidate_count: int = 1
    unknown_policy: Literal["exclude", "penalize"] = "exclude"
    unknown_penalty_factor: float = 10.0
    max_detour_ratio: float | None = None
    risk_multiplier: float = 1.0


@dataclass(frozen=True)
class PrioritySpec:
    crs: str
    population_reference: float
    grid_size_m: float = 1000.0
    origin_x_m: float = 0.0
    origin_y_m: float = 0.0
    weights: dict[str, float] = field(
        default_factory=lambda: {"damage": 1 / 3, "population": 1 / 3, "access": 1 / 3}
    )


@dataclass(frozen=True)
class DecisionRequest:
    event_id: str
    study_area: StudyArea
    road_network: Path
    rescue_points: Path
    route_options: RouteOptions
    priority_spec: PrioritySpec
    flood_result: FloodResult | None = None
    damage_results: tuple[DamageResult, ...] = ()
    review_result: ReviewResult | None = None
    population_grid: Path | None = None
    blocked_roads: Path | None = None


@dataclass(frozen=True)
class RouteResult:
    meta: ResultMeta
    routes_path: Path
    route_count: int
    unreachable_pairs: tuple[tuple[str, str], ...]
    uncertain_count: int
    cost_mode: CostMode


@dataclass(frozen=True)
class PriorityResult:
    meta: ResultMeta
    priority_areas_path: Path
    weights_used: dict[str, dict[str, float]]
    score_component_keys: tuple[str, ...]
    area_count: int


@dataclass(frozen=True)
class DecisionResult:
    artifacts: dict[str, Path]
    meta: ResultMeta


@dataclass(frozen=True)
class DecisionSnapshot:
    run_id: str
    decision_result_path: Path
    confirmed_blocked_crossings: int
    reachable_goal_count: int
    mean_distance_m: float | None
    mean_detour_ratio: float | None
    unknown_edge_length_m: float
    coverage: dict[str, float | int | None]


@dataclass(frozen=True)
class DecisionComparison:
    event_id: str
    before: DecisionSnapshot
    after: DecisionSnapshot
    inputs_and_parameters_match: bool
    comparable_pairs: tuple[tuple[str, str], ...]
    newly_reachable_goal_ids: tuple[str, ...]
    newly_unreachable_goal_ids: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MapLayerSpec:
    layer_id: str
    event_id: str
    kind: Literal["raster", "vector"]
    path: Path
    crs: str
    asset_ids: tuple[str, ...]
    title: str
    style: dict[str, JSONValue] = field(default_factory=dict)
    min_zoom: int | None = None
    max_zoom: int | None = None


@dataclass(frozen=True)
class LayerManifest:
    event_id: str
    layers: tuple[MapLayerSpec, ...]
    schema_version: Literal["2.0"] = SCHEMA_VERSION


@dataclass(frozen=True)
class MapLayer:
    """框架无关图层描述；UI 内部对象不跨角色序列化。"""
    spec: MapLayerSpec


@dataclass(frozen=True)
class MapHandle:
    map_id: str


@dataclass(frozen=True)
class FeatureDetail:
    event_id: str
    layer_id: str
    feature_id: str
    properties: dict[str, JSONValue]
    geometry: dict[str, JSONValue] | None = None


@dataclass(frozen=True)
class PipelineConfig:
    event_id: str
    stage: Stage
    study_area: StudyArea
    asset_catalog: Path
    module_configs: dict[str, dict[str, JSONValue]]
    output_dir: Path
    schema_version: Literal["2.0"] = SCHEMA_VERSION


@dataclass(frozen=True)
class PipelineRunResult:
    run_id: str
    status: Literal["success", "partial", "failed"]
    event_id: str
    stage: Stage
    artifacts: dict[str, Path]
    reports: dict[str, Path]
    started_at: datetime
    finished_at: datetime
    warnings: tuple[str, ...] = ()


ResultEnvelope: TypeAlias = FloodResult | DamageResult | ReviewResult | DecisionResult


class OrthomosaicProcessor(Protocol):
    name: str
    version: str

    def build(self, request: OrthomosaicRequest) -> RasterAsset:
        """离线调用摄影测量工具，返回带真实地理参考的正射影像。"""


class DamageModel(Protocol):
    name: str
    version: str

    def predict(
        self, request: DamageRequest, options: InferenceOptions | None = None
    ) -> DamageResult:
        """推理输出须保留模型身份、逐栋结果和切片索引。"""


class DecisionEngine(Protocol):
    name: str
    version: str

    def analyze(self, request: DecisionRequest) -> DecisionResult:
        """先计算路线，再以 RouteResult 计算重点区，返回结果引用。"""
