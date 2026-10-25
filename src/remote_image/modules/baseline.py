"""无第三方依赖的占位实现，只用于打通契约和流水线。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from remote_image.core.contracts import (
    DamageRequest,
    DamageResult,
    DecisionRequest,
    DecisionResult,
    InferenceOptions,
    OrthomosaicRequest,
    RasterAsset,
    ResultMeta,
)


@dataclass
class PlaceholderOrthomosaicProcessor:
    name: str = "placeholder_orthomosaic"

    def build(self, request: OrthomosaicRequest) -> RasterAsset:
        return RasterAsset(
            asset_id=f"{request.event_id}_placeholder_orthomosaic",
            path=request.output_dir / "orthomosaic.tif",
            acquired_at=None,
            source="placeholder",
            coordinate_reference_system=request.study_area.coordinate_reference_system,
            pixel_size_m=0.1,
            source_type="uav_orthomosaic",
            quality_notes="占位结果，不可用于实际研判",
        )


@dataclass
class PlaceholderDamageModel:
    name: str = "baseline_damage_model"
    version: str = "0.1.0"

    def predict(
        self, request: DamageRequest, options: InferenceOptions | None = None
    ) -> DamageResult:
        return DamageResult(
            artifacts={
                "damage_vector": Path("outputs/fixture/damage_vector.geojson"),
                "tile_index": Path("outputs/fixture/tile_index.geojson"),
                "metadata": Path("outputs/fixture/damage_metadata.json"),
            },
            model_name=self.name,
            model_version=self.version,
            meta=ResultMeta(
                schema_version="1.0",
                event_id=request.event_id,
                study_area_id=request.study_area.identifier,
                input_asset_ids=tuple(
                    asset.asset_id
                    for asset in (request.pre_event, request.post_event)
                    if asset is not None
                ),
                method=request.task,
                method_version=self.version,
                parameters={
                    "fixture_only": True,
                    "inference_options": vars(options) if options else {},
                },
                created_at=datetime.now(),
                warnings=("占位结果，不可用于实际研判",),
            ),
        )


@dataclass
class PlaceholderDecisionEngine:
    name: str = "baseline_decision_engine"
    version: str = "0.1.0"

    def analyze(self, request: DecisionRequest) -> DecisionResult:
        input_ids = tuple(
            asset_id
            for result in request.damage_results
            for asset_id in result.meta.input_asset_ids
        )
        return DecisionResult(
            artifacts={
                "routes": Path("outputs/fixture/candidate_routes.geojson"),
                "priority_areas": Path("outputs/fixture/priority_areas.geojson"),
                "summary": Path("outputs/fixture/summary.json"),
            },
            meta=ResultMeta(
                schema_version="1.0",
                event_id=request.event_id,
                study_area_id=request.study_area.identifier,
                input_asset_ids=input_ids,
                method="placeholder_decision",
                method_version=self.version,
                parameters={"route_options": vars(request.route_options)},
                warnings=("占位结果，不可用于实际研判",),
            ),
        )
