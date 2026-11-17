from __future__ import annotations

import shutil
import unittest
import uuid
from dataclasses import replace
from pathlib import Path

from remote_image.core.contracts import (
    DamageRequest,
    InferenceOptions,
    RasterAsset,
    StudyArea,
)
from remote_image.core.errors import ErrorCode, PipelineError
from remote_image.core.model_manifest import load_model_manifest
from remote_image.core.model_runtime import DamageRuntime
from remote_image.workflows.damage import (
    load_model,
    register_model,
    register_model_loader,
    run_damage,
)
from tests.integration.stage2_adapter import FixtureModelLoader


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "stage2_synthetic"
MANIFEST = FIXTURES / "model_manifest.json"
TEST_WORK_ROOT = ROOT / "work" / "tests"


def make_case_dir(testcase: unittest.TestCase) -> Path:
    TEST_WORK_ROOT.mkdir(parents=True, exist_ok=True)
    root = TEST_WORK_ROOT / f"case-{uuid.uuid4().hex}"
    root.mkdir()
    testcase.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
    return root


def make_request(root: Path, *, source_type: str = "satellite") -> DamageRequest:
    image = root / "post_event.tif"
    image.write_bytes(b"synthetic raster placeholder")
    boundary = root / "study_area.geojson"
    boundary.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    return DamageRequest(
        event_id="fixture_event",
        study_area=StudyArea("fixture_area", str(boundary), "EPSG:32650"),
        post_event=RasterAsset(
            asset_id="fixture_post",
            path=image,
            acquired_at=None,
            source="synthetic_fixture",
            coordinate_reference_system="EPSG:32650",
            pixel_size_m=0.5,
            bands=("R", "G", "B"),
            source_type=source_type,  # type: ignore[arg-type]
        ),
        model_name="fixture_damage_model",
        model_version="2.0.0",
        task="building_damage",
    )


class Stage2ModelManifestTests(unittest.TestCase):
    def test_manifest_paths_and_weight_hash_are_validated(self) -> None:
        manifest = load_model_manifest(MANIFEST, project_root=ROOT)
        self.assertTrue(manifest.weights_path.is_absolute())
        self.assertTrue(manifest.weights_path.is_file())
        self.assertTrue(manifest.evaluation_path.is_file())
        self.assertEqual(manifest.model_name, "fixture_damage_model")

    def test_weight_hash_mismatch_has_stable_error(self) -> None:
        with self.assertRaises(PipelineError) as captured:
            load_model_manifest(
                FIXTURES / "model_manifest_bad_hash.json",
                project_root=ROOT,
            )
        self.assertEqual(captured.exception.code, ErrorCode.MODEL_LOAD_FAILED)
        self.assertIn("SHA-256", captured.exception.message)


class C1Stage2RuntimeTests(unittest.TestCase):
    def _build_runtime(self, adapter_options: dict[str, object] | None = None):
        root = make_case_dir(self)
        runtime = DamageRuntime(project_root=ROOT)
        loader = FixtureModelLoader(root / "outputs", **(adapter_options or {}))
        runtime.register_model_loader("fixture_damage_model", "2.0.0", loader)
        adapter = runtime.load_model(MANIFEST, device="cpu")
        runtime.register_model(adapter.name, adapter.version, adapter)
        return runtime, loader, make_request(root)

    def test_defaults_and_request_overrides_are_merged(self) -> None:
        runtime, loader, request = self._build_runtime()
        result = runtime.run_damage(
            request,
            InferenceOptions(tile_size_px=512, batch_size=1),
        )
        effective = result.meta.parameters["inference_options"]
        self.assertEqual(loader.calls, 1)
        self.assertEqual(effective["tile_size_px"], 512)
        self.assertEqual(effective["overlap_ratio"], 0.2)
        self.assertEqual(effective["confidence_threshold"], 0.5)
        self.assertEqual(effective["device"], "cpu")
        self.assertEqual(effective["batch_size"], 1)
        self.assertEqual(result.model_version, "2.0.0")

    def test_request_cannot_exceed_manifest_limits(self) -> None:
        runtime, _, request = self._build_runtime()
        with self.assertRaises(PipelineError) as captured:
            runtime.run_damage(request, InferenceOptions(tile_size_px=64))
        self.assertEqual(captured.exception.code, ErrorCode.INPUT_INVALID)
        self.assertEqual(captured.exception.details["field"], "tile_size_px")

    def test_unsupported_sensor_is_rejected_before_predict(self) -> None:
        runtime, loader, request = self._build_runtime()
        with self.assertRaises(PipelineError) as captured:
            runtime.run_damage(replace(request, post_event=replace(
                request.post_event, source_type="uav_orthomosaic"
            )))
        self.assertEqual(captured.exception.code, ErrorCode.INPUT_INVALID)
        self.assertIsNotNone(loader.adapter)
        self.assertEqual(loader.adapter.predict_calls, 0)

    def test_unregistered_loader_and_version_have_stable_errors(self) -> None:
        runtime = DamageRuntime(project_root=ROOT)
        with self.assertRaises(PipelineError) as captured:
            runtime.load_model(MANIFEST)
        self.assertEqual(captured.exception.code, ErrorCode.MODEL_LOAD_FAILED)

        request = replace(
            make_request(make_case_dir(self)),
            model_version="9.9.9",
        )
        with self.assertRaises(PipelineError) as captured:
            runtime.run_damage(request)
        self.assertEqual(captured.exception.code, ErrorCode.MODEL_NOT_REGISTERED)

    def test_invalid_damage_class_is_rejected_before_handoff(self) -> None:
        runtime, _, request = self._build_runtime({"damage_class": "invalid-class"})
        with self.assertRaises(PipelineError) as captured:
            runtime.run_damage(request)
        self.assertEqual(captured.exception.code, ErrorCode.RESULT_INVALID)
        self.assertTrue(captured.exception.details["errors"])

    def test_geopackage_properties_are_validated_without_gis_dependency(self) -> None:
        runtime, _, request = self._build_runtime({"artifact_format": "gpkg"})
        result = runtime.run_damage(request)
        self.assertEqual(result.artifacts["damage_vector"].suffix, ".gpkg")
        self.assertEqual(result.artifacts["tile_index"].suffix, ".gpkg")

    def test_corrupt_geopackage_has_stable_result_error(self) -> None:
        runtime, _, request = self._build_runtime(
            {"artifact_format": "gpkg", "corrupt_gpkg": True}
        )
        with self.assertRaises(PipelineError) as captured:
            runtime.run_damage(request)
        self.assertEqual(captured.exception.code, ErrorCode.RESULT_INVALID)
        self.assertTrue(captured.exception.details["errors"])

    def test_public_workflow_entrypoints_are_callable(self) -> None:
        root = make_case_dir(self)
        loader = FixtureModelLoader(root / "outputs")
        register_model_loader("fixture_damage_model", "2.0.0", loader)
        adapter = load_model(MANIFEST, device="cpu")
        register_model(adapter.name, adapter.version, adapter)
        result = run_damage(make_request(root))
        self.assertEqual(result.model_name, "fixture_damage_model")


if __name__ == "__main__":
    unittest.main()
