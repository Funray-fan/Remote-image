"""最小可运行示例。"""

from datetime import datetime
from pathlib import Path

from remote_image.core.contracts import RasterAsset, StudyArea
from remote_image.core.registry import PluginRegistry
from remote_image.modules.baseline import PlaceholderDamageModel, PlaceholderDecisionEngine
from remote_image.workflows.assessment import AssessmentWorkflow


def build_registry() -> PluginRegistry:
    registry = PluginRegistry()
    registry.register("baseline_damage_model", PlaceholderDamageModel())
    registry.register("baseline_decision_engine", PlaceholderDecisionEngine())
    return registry


def main() -> None:
    registry = build_registry()
    workflow = AssessmentWorkflow(registry)
    study_area = StudyArea(
        identifier="fixture_area",
        boundary="tests/fixtures/contracts/study_area.geojson",
        coordinate_reference_system="EPSG:4326",
    )
    result = workflow.run(
        event_id="fixture_event",
        study_area=study_area,
        post_event=RasterAsset(
            asset_id="fixture_post_event",
            path=Path("data/post_event_orthomosaic.tif"),
            acquired_at=datetime.now(),
            source="uav",
            coordinate_reference_system="EPSG:4326",
            pixel_size_m=0.1,
            source_type="uav_orthomosaic",
        ),
        pre_event=None,
        building_footprints=Path("data/buildings.geojson"),
        road_network=Path("data/roads.geojson"),
        rescue_points=Path("data/rescue_points.geojson"),
        population_grid=Path("data/population.tif"),
    )
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()

