"""跨模块稳定接口 v1。

公共对象只在此处和 ``schemas/v1`` 定义。业务模块不得复制或私自扩展同名对象；
不兼容变更必须提升 schema 版本并提供迁移说明。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol


JSONValue = Any
DamageTask = Literal["building_damage", "building_segmentation"]
DamageClass = Literal[
    "no-damage",
    "minor-damage",
    "major-damage",
    "destroyed",
    "un-classified",
]


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
    status: Literal["planned", "verified", "acquired", "usable"]
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
    source_type: Literal[
        "satellite", "uav_orthomosaic", "public_orthomosaic"
    ] = "satellite"
    is_substitute: bool = False
    quality_notes: str | None = None


@dataclass(frozen=True)
class ResultMeta:
    schema_version: str
    event_id: str
    study_area_id: str
    input_asset_ids: tuple[str, ...]
    method: str
    method_version: str
    parameters: dict[str, JSONValue] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class InferenceOptions:
    tile_size_px: int | None = None
    overlap_ratio: float | None = None
    confidence_threshold: float | None = None
    device: str | None = None
    batch_size: int | None = None


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
class DamageRequest:
    event_id: str
    study_area: StudyArea
    post_event: RasterAsset
    pre_event: RasterAsset | None = None
    building_footprints: Path | None = None
    model_name: str = "baseline"
    task: DamageTask = "building_damage"


@dataclass(frozen=True)
class DamageResult:
    artifacts: dict[str, Path]
    model_name: str
    model_version: str
    meta: ResultMeta


@dataclass(frozen=True)
class FloodResult:
    artifacts: dict[str, Path]
    meta: ResultMeta


@dataclass(frozen=True)
class ReviewResult:
    artifacts: dict[str, Path]
    meta: ResultMeta


@dataclass(frozen=True)
class RouteOptions:
    start_ids: tuple[str, ...]
    goal_ids: tuple[str, ...]
    cost_mode: Literal["distance", "time", "risk_weighted"] = "distance"
    blocked_policy: Literal["exclude", "penalize"] = "exclude"
    candidate_count: int = 1
    damage_weight: float = 1 / 3
    population_weight: float = 1 / 3
    access_weight: float = 1 / 3
    blocked_penalty_factor: float = 10.0
    max_detour_ratio: float | None = None
    risk_multiplier: float = 1.0


@dataclass(frozen=True)
class DecisionRequest:
    event_id: str
    study_area: StudyArea
    road_network: Path
    rescue_points: Path
    route_options: RouteOptions
    flood_result: FloodResult | None = None
    damage_results: tuple[DamageResult, ...] = ()
    review_result: ReviewResult | None = None
    population_grid: Path | None = None
    blocked_roads: Path | None = None


@dataclass(frozen=True)
class DecisionResult:
    artifacts: dict[str, Path]
    meta: ResultMeta


class OrthomosaicProcessor(Protocol):
    name: str

    def build(self, request: OrthomosaicRequest) -> RasterAsset:
        """将航片处理成带地理参考的正射影像。"""


class DamageModel(Protocol):
    name: str

    def predict(
        self, request: DamageRequest, options: InferenceOptions | None = None
    ) -> DamageResult:
        """进行建筑分割或建筑灾损推理。"""


class DecisionEngine(Protocol):
    name: str

    def analyze(self, request: DecisionRequest) -> DecisionResult:
        """生成优先区域和候选救援路线。"""
