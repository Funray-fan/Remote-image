from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from remote_image.core.contracts import (
    DamageRequest,
    DecisionRequest,
    InferenceOptions,
    PrioritySpec,
    RasterAsset,
    RouteOptions,
    StudyArea,
)
from remote_image.core.registry import PluginRegistry


@dataclass
class AssessmentWorkflow:
    registry: PluginRegistry

    def run(
        self,
        *,
        event_id: str,
        study_area: StudyArea,
        post_event: RasterAsset,
        pre_event: RasterAsset | None,
        building_footprints: Path | None,
        road_network: Path,
        rescue_points: Path,
        population_grid: Path | None = None,
        damage_model_name: str = "baseline_damage_model",
        damage_model_version: str = "0.2.0",
        decision_engine_name: str = "baseline_decision_engine",
    ) -> dict[str, str]:
        model = self.registry.get(damage_model_name)
        damage = model.predict(
            DamageRequest(
                event_id=event_id,
                study_area=study_area,
                post_event=post_event,
                pre_event=pre_event,
                building_footprints=building_footprints,
                model_name=damage_model_name,
                model_version=damage_model_version,
            ),
            InferenceOptions(device="cpu", batch_size=1),
        )
        engine = self.registry.get(decision_engine_name)
        decision = engine.analyze(
            DecisionRequest(
                event_id=event_id,
                study_area=study_area,
                damage_results=(damage,),
                road_network=road_network,
                rescue_points=rescue_points,
                population_grid=population_grid,
                route_options=RouteOptions(
                    start_ids=("start",),
                    goal_ids=("goal",),
                    as_of=datetime.now(timezone.utc),
                ),
                priority_spec=PrioritySpec(
                    crs=study_area.coordinate_reference_system,
                    population_reference=1.0,
                ),
            )
        )
        return {
            "damage_result": str(damage.artifacts["damage_vector"]),
            "candidate_routes": str(decision.artifacts["routes"]),
            "priority_areas": str(decision.artifacts["priority_areas"]),
            "summary": str(decision.artifacts["summary"]),
        }
