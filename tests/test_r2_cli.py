"""R2 CLI 的来源缓存、配置快照与冻结参数回归，不运行真实案例。"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import time
import unittest

from remote_image.core.contracts import FloodOptions, ThresholdReport
from remote_image.core.validation import validate_contract
from remote_image.modules.flood.cli import (
    cache_fingerprint, load_config, resolve, snapshot_config, validate_selection,
)
from remote_image.modules.flood.qa import R2Error, write_json

ROOT = Path(__file__).resolve().parents[1]


class R2CliTests(unittest.TestCase):
    def setUp(self):
        work = ROOT / "work"
        work.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=work, prefix="r2-cli-test-")
        self.addCleanup(self.cleanup_temp)
        self.project = Path(self.temp.name) / "project"
        config_path = self.project / "configs" / "r2" / "synthetic.json"
        self.config_data = {
            "r2_config_version": "1.0", "project_root": "../..",
            "event_id": "synthetic_event",
            "input": {"backscatter_quantity": "gamma0", "value_scale": "linear_power",
                      "polarization": "VV", "pre_path": "data/raw/pre.tif"},
            "analysis": {"connectivity": 4, "aoi_kind": "raster_extent",
                         "selected_water_threshold_db": -20, "min_patch_area_m2": 0},
        }
        write_json(config_path, self.config_data)
        self.cfg = load_config(config_path)
        self.option = FloodOptions(("VV",), {"VV": -20}, {"VV": -20}, "single", min_patch_area_m2=0)

    def cleanup_temp(self):
        for attempt in range(4):
            try:
                self.temp.cleanup()
                return
            except OSError as error:
                if attempt == 3 or getattr(error, "winerror", None) not in (32, 145):
                    raise
                time.sleep(0.1)

    def write_selection_report(self):
        report = ThresholdReport(
            status="warning", checks=(),
            metrics={"precision": None, "recall": None, "f1": None, "iou": None},
            warnings=("合成测试样例，不表示真实精度。",), artifacts={},
            candidate_options=(self.option,), selected_options=self.option,
            reference_available=False,
            selection_reason="无参考标签，合成测试显式采用第 0 项试运行参数。",
        )
        validate_contract(report)
        report_path = self.project / "work" / "r2" / "evaluations" / "fixture" / "threshold_report.json"
        write_json(report_path, report)
        self.cfg["selection"] = {"evaluation_report": report_path.relative_to(self.project).as_posix()}
        return report_path

    def test_source_revision_is_part_of_the_prepared_cache_identity(self):
        hashes = {"pre_event": "a" * 64, "post_event": "b" * 64, "valid_mask": "c" * 64}
        first = cache_fingerprint(hashes, "d" * 64, "source_revision_a")
        different_revision = cache_fingerprint(hashes, "d" * 64, "source_revision_b")
        self.assertNotEqual(first, different_revision)
        self.assertEqual(first, cache_fingerprint(dict(reversed(list(hashes.items()))), "d" * 64, "source_revision_a"))
        self.assertNotEqual(first, cache_fingerprint(hashes, "e" * 64, "source_revision_a"))

    def test_deep_output_config_snapshot_keeps_the_original_project_root(self):
        destination = self.project / "outputs" / "synthetic_event" / "stage1" / "r2" / "run_fixture" / "resolved_config.json"
        saved = snapshot_config(self.cfg, destination)
        self.assertNotIn("_project_root", saved)
        self.assertNotIn("_config_path", saved)
        self.assertFalse(Path(saved["project_root"]).is_absolute())
        write_json(destination, saved)
        loaded_again = load_config(destination)
        self.assertEqual(Path(loaded_again["_project_root"]), self.project.resolve())
        self.assertEqual(resolve(loaded_again, loaded_again["input"]["pre_path"]),
                         resolve(self.cfg, self.cfg["input"]["pre_path"]))
        self.assertEqual(Path(loaded_again["_config_path"]), destination.resolve())

    def test_frozen_options_must_match_the_selection_report(self):
        report_path = self.write_selection_report()
        self.assertEqual(validate_selection(self.cfg, self.option), report_path.resolve())
        changed = (
            replace(self.option, min_patch_area_m2=200),
            replace(self.option, post_thresholds_db={"VV": -18}, pre_water_thresholds_db={"VV": -18}),
        )
        for option in changed:
            with self.subTest(option=option), self.assertRaises(R2Error) as found:
                validate_selection(self.cfg, option)
            self.assertEqual(found.exception.code, "STALE_SELECTION")

    def test_missing_frozen_selection_report_is_rejected(self):
        self.cfg["selection"] = {"evaluation_report": "work/r2/evaluations/absent/threshold_report.json"}
        with self.assertRaises(R2Error) as found:
            validate_selection(self.cfg, self.option)
        self.assertEqual(found.exception.code, "MISSING_SELECTION_REPORT")


if __name__ == "__main__":
    unittest.main()
