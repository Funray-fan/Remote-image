from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from remote_image.core.config import ConfigError, load_config
from remote_image.core.validation import validate_result, validate_against_schema
from remote_image.core.metadata import write_metadata
from remote_image.core.manifest import build_manifest
from remote_image.core.contracts import ResultMeta
from remote_image.workflows.stage1 import run_pipeline


class C1Stage1Tests(unittest.TestCase):
    def test_load_config_and_resolve_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "configs").mkdir()
            config_file = root / "configs" / "run.json"
            config_file.write_text(json.dumps({
                "event_id": "e1", "study_area_id": "a1",
                "output_dir": "outputs", "steps": []
            }), encoding="utf-8")
            config = load_config(config_file)
            self.assertEqual(config["output_dir"], root / "outputs")

    def test_reject_missing_and_duplicate_steps(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bad = root / "bad.json"
            bad.write_text(json.dumps({"event_id": "e1"}), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(bad)

            dup = root / "duplicate.json"
            dup.write_text(json.dumps({
                "event_id": "e1", "study_area_id": "a1",
                "output_dir": "outputs",
                "steps": [
                    {"name": "same", "callable": "remote_image.modules.baseline:run"},
                    {"name": "same", "callable": "remote_image.modules.baseline:run"}
                ]
            }), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(dup)

    def test_empty_pipeline_is_warning_and_writes_relative_summary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = {
                "event_id": "e1", "study_area_id": "a1",
                "output_dir": root / "outputs", "_project_root": root,
                "steps": []
            }
            result = run_pipeline(config)
            self.assertEqual(result["status"], "warning")
            self.assertEqual(result["output_dir"], "outputs/e1/stage1")
            summary = root / "outputs/e1/stage1/summary.json"
            self.assertTrue(summary.is_file())
            saved = json.loads(summary.read_text(encoding="utf-8"))
            self.assertNotIn(str(root), summary.read_text(encoding="utf-8"))

    def test_failed_module_is_recorded_and_pipeline_stops(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = {
                "event_id": "e1", "study_area_id": "a1",
                "output_dir": root / "outputs", "_project_root": root,
                "steps": [{
                    "name": "missing_module",
                    "callable": "remote_image.modules.module_does_not_exist:run",
                    "kwargs": {}
                }, {
                    "name": "should_not_run",
                    "callable": "remote_image.modules.baseline:run",
                    "kwargs": {}
                }]
            }
            result = run_pipeline(config)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["errors"][0]["step"], "missing_module")
            self.assertEqual(len(result["steps"]), 1)

    def test_result_artifact_and_metadata_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = root / "flood_mask.tif"
            artifact.write_bytes(b"test fixture")
            good = {
                "artifacts": {"flood_mask": artifact},
                "meta": {
                    "schema_version": "1.0", "event_id": "e1",
                    "study_area_id": "a1", "input_asset_ids": ["asset1"],
                    "method": "rule_baseline", "method_version": "0.1"
                }
            }
            self.assertEqual(
                validate_result(good, required_artifacts=("flood_mask",))["status"],
                "pass"
            )
            self.assertEqual(
                validate_result(good, required_artifacts=("flood_mask", "metadata"))["status"],
                "fail"
            )

    def test_existing_repository_schema_validation(self):
        root = Path(__file__).resolve().parents[2]
        fixture_path = root / "tests/fixtures/contracts/stage_result_manifest_valid.json"
        schema_path = root / "schemas/v1/stage-result-manifest.schema.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertEqual(
            validate_against_schema(fixture, schema_path)["status"], "pass"
        )


    def test_write_metadata_from_public_result_meta(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            meta = ResultMeta("1.0", "e1", "a1", ("asset1",), "baseline", "0.1")
            path = write_metadata(meta, root / "metadata.json")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["event_id"], "e1")
            self.assertEqual(saved["input_asset_ids"], ["asset1"])

    def test_build_manifest_schema_and_file_hash(self):
        import hashlib
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = root / "summary.json"
            artifact.write_text('{"status":"pass"}', encoding="utf-8")
            schema = Path(__file__).resolve().parents[2] / "schemas/v1/stage-result-manifest.schema.json"
            manifest = build_manifest(
                event_id="e1", stage="stage1", input_asset_ids=["asset1"],
                method="stage1_pipeline", artifacts={"stage_summary": artifact},
                output_path=root / "manifest.json", project_root=root,
                run_command="python -m remote_image.workflows.stage1",
                tests=[{"name": "smoke", "status": "pass"}], schema_path=schema,
            )
            self.assertEqual(manifest["files"][0]["sha256"],
                             hashlib.sha256(b'{"status":"pass"}').hexdigest())
            self.assertTrue((root / "manifest.json").is_file())

    def test_manifest_requires_real_input_asset_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = root / "summary.json"
            artifact.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_manifest(
                    event_id="e1", stage="stage1", input_asset_ids=[],
                    method="test", artifacts={"summary": artifact},
                    output_path=root / "manifest.json", project_root=root,
                    run_command="test", tests=[{"name": "t", "status": "pass"}],
                )


if __name__ == "__main__":
    unittest.main()
