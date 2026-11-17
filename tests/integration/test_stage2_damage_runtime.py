from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from remote_image.core.contracts import (
    DamageRequest,
    InferenceOptions,
    RasterAsset,
    StudyArea,
)
from remote_image.core.damage_runtime import DamageRuntime, validate_damage_result
from remote_image.core.errors import ErrorCode, PipelineError
from remote_image.workflows.damage import load_model, register_model, run_damage


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "contracts"
MANIFEST = FIXTURES / "model_manifest_valid.json"


def make_request() -> DamageRequest:
    return DamageRequest(
        event_id="fixture_event",
        study_area=StudyArea(
            identifier="fixture_area",
            boundary=str(FIXTURES / "study_area.geojson"),
            coordinate_reference_system="EPSG:4326",
        ),
        post_event=RasterAsset(
            asset_id="fixture_post_event",
            path=FIXTURES / "post_event.tif",
            acquired_at=datetime(2026, 11, 17),
            source="synthetic_fixture",
            coordinate_reference_system="EPSG:4326",
            pixel_size_m=10.0,
            bands=("VV",),
        ),
        building_footprints=FIXTURES / "buildings.geojson",
        model_name="fixture_damage_model",
        task="building_damage",
    )


class Stage2DamageRuntimeTests(unittest.TestCase):
    def test_load_register_and_run_merges_defaults_with_request_overrides(self) -> None:
        runtime = DamageRuntime()
        adapter = runtime.load_model(MANIFEST, device="cpu")
        runtime.register_model(adapter.name, adapter)

        result = runtime.run_damage(
            make_request(),
            InferenceOptions(tile_size_px=512, batch_size=4),
        )

        options = result.meta.parameters["inference_options"]
        self.assertEqual(options["tile_size_px"], 512)
        self.assertEqual(options["overlap_ratio"], 0.25)
        self.assertEqual(options["confidence_threshold"], 0.5)
        self.assertEqual(options["device"], "cpu")
        self.assertEqual(options["batch_size"], 4)
        self.assertEqual(result.model_name, "fixture_damage_model")
        self.assertEqual(result.model_version, "1.0.0")
        self.assertTrue(result.artifacts["damage_vector"].is_file())

    def test_public_entrypoints_are_runnable(self) -> None:
        adapter = load_model(MANIFEST)
        register_model(adapter.name, adapter)
        result = run_damage(make_request())
        self.assertEqual(result.model_version, "1.0.0")

    def test_unregistered_model_fails_with_stable_error(self) -> None:
        runtime = DamageRuntime()
        with self.assertRaises(PipelineError) as captured:
            runtime.run_damage(make_request())
        self.assertEqual(captured.exception.code, ErrorCode.MODEL_LOAD_FAILED)
        self.assertEqual(
            captured.exception.to_dict()["code"], "MODEL_LOAD_FAILED"
        )

    def test_request_cannot_exceed_manifest_tile_limit(self) -> None:
        runtime = DamageRuntime()
        adapter = runtime.load_model(MANIFEST)
        runtime.register_model(adapter.name, adapter)

        with self.assertRaises(PipelineError) as captured:
            runtime.run_damage(
                make_request(),
                InferenceOptions(tile_size_px=64),
            )
        self.assertEqual(captured.exception.code, ErrorCode.INPUT_INVALID)
        self.assertEqual(captured.exception.details["field"], "tile_size_px")

    def test_invalid_inference_option_type_has_stable_error(self) -> None:
        runtime = DamageRuntime()
        adapter = runtime.load_model(MANIFEST)
        runtime.register_model(adapter.name, adapter)

        with self.assertRaises(PipelineError) as captured:
            runtime.run_damage(
                make_request(),
                InferenceOptions(tile_size_px="256"),  # type: ignore[arg-type]
            )
        self.assertEqual(captured.exception.code, ErrorCode.INPUT_INVALID)

    def test_weight_hash_mismatch_is_model_load_failure(self) -> None:
        with self.assertRaises(PipelineError) as captured:
            DamageRuntime().load_model(FIXTURES / "model_manifest_bad_hash.json")
        self.assertEqual(captured.exception.code, ErrorCode.MODEL_LOAD_FAILED)
        self.assertEqual(captured.exception.message, "模型权重 SHA-256 校验失败")

    def test_invalid_damage_class_is_rejected_before_handoff(self) -> None:
        runtime = DamageRuntime()
        adapter = runtime.load_model(MANIFEST)
        runtime.register_model(adapter.name, adapter)
        result = runtime.run_damage(make_request())
        invalid_result = replace(
            result,
            artifacts={
                **result.artifacts,
                "damage_vector": FIXTURES / "damage_vector_invalid_class.geojson",
            },
        )

        report = validate_damage_result(
            invalid_result,
            make_request(),
            adapter.manifest,
        )

        self.assertFalse(report.valid)
        self.assertTrue(
            any("damage_class" in message for message in report.errors),
            report.errors,
        )


if __name__ == "__main__":
    unittest.main()
