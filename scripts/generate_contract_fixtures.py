"""生成不会冒充真实灾情的 v2 合成契约样例。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "contracts_v2"
T = "2026-10-26T12:00:00+08:00"


def asset(asset_id: str, role: str) -> dict:
    return {
        "asset_id": asset_id,
        "path": f"synthetic/{role}.tif",
        "acquired_at": T,
        "source": "synthetic_fixture",
        "coordinate_reference_system": "EPSG:32650",
        "pixel_size_m": 0.5,
        "bands": ["VV", "VH", "R", "G", "B"],
        "footprint": None,
        "source_type": "satellite",
        "is_substitute": False,
        "quality_notes": "synthetic contract fixture only",
    }


def meta(method: str = "building_damage") -> dict:
    return {
        "schema_version": "2.0",
        "event_id": "synthetic_event",
        "study_area_id": "synthetic_area",
        "input_asset_ids": ["synthetic_post"],
        "method": method,
        "method_version": "0.0.0-fixture",
        "parameters": {"fixture_only": True},
        "created_at": T,
        "warnings": ["synthetic fixture; not a scientific result"],
    }


def with_version(value: dict) -> dict:
    return {"schema_version": "2.0", **value}


def main() -> None:
    pre, post = asset("synthetic_pre", "pre_event"), asset("synthetic_post", "post_event")
    area = {"identifier": "synthetic_area", "boundary": "synthetic/study_area.geojson", "coordinate_reference_system": "EPSG:32650"}
    grid = {"transform": [0.5, 0.0, 500000.0, 0.0, -0.5, 4400000.0], "width": 32, "height": 32, "pixel_size_x_m": 0.5, "pixel_size_y_m": 0.5}
    options = {"polarizations": ["VV", "VH"], "post_thresholds_db": {"VV": -16.0, "VH": -23.0}, "pre_water_thresholds_db": {"VV": -15.0, "VH": -22.0}, "polarization_rule": "all", "permanent_water_mask": None, "exclusion_mask": None, "min_patch_area_m2": 20.0, "method": "sar_post_threshold"}
    damage_result = {"artifacts": {"damage_vector": "synthetic/damage_vector.geojson", "tile_index": "synthetic/tile_index.geojson", "metadata": "synthetic/damage_meta.json"}, "model_name": "synthetic_xbd_model", "model_version": "0.0.0-fixture", "meta": meta()}
    flood_result = {"artifacts": {"flood_mask": "synthetic/flood_mask.tif", "flood_polygons": "synthetic/flood.geojson", "metadata": "synthetic/flood_meta.json"}, "meta": meta("sar_post_threshold")}
    review_result = {"artifacts": {"review_table": "synthetic/review.csv", "review_layer": "synthetic/review.geojson", "road_state_updates": "synthetic/road_updates.geojson", "metadata": "synthetic/review_meta.json"}, "meta": meta("manual_uav_review")}
    route_options = {"start_ids": ["base-1"], "goal_ids": ["target-1"], "as_of": T, "cost_mode": "distance", "blocked_policy": "exclude", "candidate_count": 2, "unknown_policy": "penalize", "unknown_penalty_factor": 10.0, "max_detour_ratio": 2.0, "risk_multiplier": 1.0}
    priority = {"crs": "EPSG:32650", "population_reference": 1000.0, "grid_size_m": 1000.0, "origin_x_m": 500000.0, "origin_y_m": 4400000.0, "weights": {"damage": 0.4, "population": 0.3, "access": 0.3}}
    cases: dict[str, dict] = {
        "flood-options": with_version(options),
        "flood-request": with_version({"event_id": "synthetic_event", "study_area": area, "inputs": {"pre_event": pre, "post_event": post, "study_area_id": "synthetic_area", "grid": grid, "valid_mask": "synthetic/valid_mask.tif"}, "options": options, "output_dir": "synthetic/output/stage1"}),
        "orthomosaic-request": with_version({"event_id": "synthetic_event", "study_area": area, "image_directory": "synthetic/uav_photos", "positioning_source": "GNSS", "control_source": "none", "ground_control_points": None, "output_dir": "synthetic/output/orthomosaic"}),
        "damage-request": with_version({"event_id": "synthetic_event", "study_area": area, "post_event": post, "model_name": "synthetic_xbd_model", "model_version": "0.0.0-fixture", "pre_event": pre, "building_footprints": "synthetic/buildings.geojson", "task": "building_damage"}),
        "damage-result": with_version(damage_result),
        "flood-result": with_version(flood_result),
        "review-result": with_version(review_result),
        "route-options": with_version(route_options),
        "priority-spec": with_version(priority),
        "decision-request": with_version({"event_id": "synthetic_event", "study_area": area, "road_network": "synthetic/roads.gpkg", "rescue_points": "synthetic/rescue_points.geojson", "route_options": route_options, "priority_spec": priority, "flood_result": None, "damage_results": [], "review_result": None, "population_grid": "synthetic/population.tif", "blocked_roads": "synthetic/road_states.gpkg"}),
        "review-spec": with_version({"event_id": "synthetic_event", "review_as_of": T, "sample_n": 180, "road_sample_n": 30, "seed": 42, "sampling_strategy": "stratified_area"}),
        "review-record": with_version({"event_id": "synthetic_event", "object_type": "building", "object_id": "building-1", "review_status": "reviewed", "damage_class": "minor-damage", "road_status": None, "confirmation": "confirmed", "source": "synthetic_fixture", "evidence_uri": "synthetic/evidence/building-1.png", "reviewer_id": "fixture-reviewer", "reviewed_at": T, "expires_at": None, "notes": "synthetic fixture only"}),
        "layer-manifest": with_version({"event_id": "synthetic_event", "layers": [{"layer_id": "synthetic-flood", "event_id": "synthetic_event", "kind": "vector", "path": "synthetic/flood.geojson", "crs": "EPSG:32650", "asset_ids": ["synthetic_post"], "title": "Synthetic flood", "style": {"color": "#0077aa"}, "min_zoom": None, "max_zoom": None}]}),
        "inference-options": with_version({"tile_size_px": 512, "overlap_ratio": 0.25, "confidence_threshold": 0.5, "device": "cpu", "batch_size": 1}),
        "dataset-manifest": with_version({"dataset_name": "synthetic_xbd_subset", "dataset_version": "0.0.0-fixture", "items": [{"sample_id": "sample-1", "event_id": "synthetic_training_event", "scene_id": "scene-1", "image_pair_id": "pair-1", "group_id": "group-1", "split": "train", "pre_event_path": "synthetic/train_pre.png", "post_event_path": "synthetic/train_post.png", "label_path": "synthetic/train_label.json", "footprint_path": None, "source": "synthetic_fixture", "license_id": "fixture-only"}], "source_url": "https://example.invalid/synthetic", "license_id": "fixture-only", "split_strategy": "scene_or_image_pair", "spatial_overlap_checked": False, "overlap_report_path": None}),
    }
    damage_vector = {"schema_version": "2.0", "type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}, "properties": {"event_id": "synthetic_event", "study_area_id": "synthetic_area", "building_id": "building-1", "damage_class": "minor-damage", "confidence": 0.75, "reason": None, "model_name": "synthetic_xbd_model", "model_version": "0.0.0-fixture"}}]}
    tile_index = {"schema_version": "2.0", "type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}, "properties": {"event_id": "synthetic_event", "study_area_id": "synthetic_area", "tile_id": "tile-0-0", "row": 0, "column": 0}}]}
    cases["damage-vector"] = damage_vector
    cases["tile-index"] = tile_index
    invalid = dict(cases["damage-request"])
    invalid["schema_version"] = "1.0"
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"description": "Synthetic interface fixtures only; not scientific outputs.", "cases": []}
    for name, payload in cases.items():
        filename = f"{name.replace('-', '_')}_valid.json"
        (OUT / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest["cases"].append({"schema": name, "file": filename, "valid": True})
    (OUT / "damage_request_invalid_v1.json").write_text(json.dumps(invalid, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest["cases"].append({"schema": "damage-request", "file": "damage_request_invalid_v1.json", "valid": False})
    (OUT / "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"生成 {len(manifest['cases'])} 个合成契约样例")


if __name__ == "__main__":
    main()
