"""R1 输入适配的合成栅格测试，不用真实灾情标签。"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import tempfile
import time
import unittest

import numpy as np
import rasterio
from rasterio.transform import from_origin

from remote_image.core.contracts import PreparedInputs
from remote_image.core.serialization import from_payload
from remote_image.modules.flood.input_io import (
    DB_NODATA, check_analysis_inputs, inspect_linear_inputs, prepare_analysis_inputs,
)
from remote_image.modules.flood.qa import R2Error, sha256_file

ROOT = Path(__file__).resolve().parents[1]


class R2InputTests(unittest.TestCase):
    def setUp(self):
        work = ROOT / "work"
        work.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=work, prefix="r2-input-test-")
        self.addCleanup(self.cleanup_temp)
        self.root = Path(self.temp.name)
        self.transform = from_origin(500000, 4400000, 10, 10)
        self.pre = self.root / "pre.tif"
        self.post = self.root / "post.tif"
        self.mask = self.root / "mask.tif"
        self.manifest = self.root / "prepared_inputs.json"
        self.values = np.array([[0.01, 1.0, 10.0], [0.1, 0.2, 0.5]], dtype="float32")
        self.write(self.pre, self.values)
        self.write(self.post, self.values * 2)
        self.write(self.mask, np.ones(self.values.shape, dtype="uint8"), nodata=0, description="valid_pre_post")
        self.payload = self.make_manifest()
        self.save_manifest()

    def cleanup_temp(self):
        # Windows 的扫描程序可能短暂占用新写入的 TIFF；重试后仍失败就报告。
        for attempt in range(4):
            try:
                self.temp.cleanup()
                return
            except OSError as error:
                if attempt == 3 or getattr(error, "winerror", None) not in (32, 145):
                    raise
                time.sleep(0.1)

    def write(self, path, values, *, nodata=DB_NODATA, transform=None, description="VV", crs="EPSG:32650", tags=None):
        with rasterio.open(path, "w", driver="GTiff", height=values.shape[0], width=values.shape[1], count=1, dtype=values.dtype, crs=crs, transform=transform or self.transform, nodata=nodata) as ds:
            ds.write(values, 1)
            ds.set_band_description(1, description)
            if tags:
                ds.update_tags(**tags)

    def make_manifest(self):
        assets = []
        for name, date in (("pre", "2023-07-24T10:00:00Z"), ("post", "2023-08-05T10:00:00+00:00")):
            assets.append({"asset_id": "synthetic_" + name, "path": name + ".tif", "acquired_at": date,
                           "source": "synthetic gamma0 fixture", "coordinate_reference_system": "EPSG:32650",
                           "pixel_size_m": 10.0, "bands": ["VV"], "footprint": None,
                           "source_type": "satellite", "is_substitute": False, "quality_notes": "synthetic",
                           "width": 3, "height": 2, "count": 1, "transform": list(self.transform)})
        return {"pre_event": assets[0], "post_event": assets[1], "study_area_id": "synthetic_area",
                "grid": {"transform": list(self.transform), "width": 3, "height": 2, "pixel_size_x_m": 10.0, "pixel_size_y_m": 10.0},
                "valid_mask": "mask.tif", "metadata": "legacy_metadata.json"}

    def save_manifest(self):
        self.manifest.write_text(json.dumps(self.payload), encoding="utf-8")

    def prepare(self, dirname="derived", **kwargs):
        return prepare_analysis_inputs(self.manifest, self.pre, self.post, self.mask, self.root / dirname, source_revision="synthetic_revision", **kwargs)

    def test_inspection_checks_actual_grid_and_known_valid_count(self):
        report = inspect_linear_inputs(self.pre, self.post, self.mask, expected={"crs": "EPSG:32650", "width": 3, "height": 2, "joint_valid_pixels": 6, "polarization": "VV"})
        self.assertEqual(report["counts"]["joint_valid_pixels"], 6)
        self.assertEqual(report["grid"]["pixel_area_m2"], 100.0)
        self.assertEqual(report["joint_valid_percent_of_rectangular_grid"], 100)
        with self.assertRaises(R2Error) as found:
            inspect_linear_inputs(self.pre, self.post, self.mask, expected={"width": 4})
        self.assertEqual(found.exception.code, "INPUT_EXPECTATION_MISMATCH")

    def test_conservative_source_mask_is_preserved(self):
        mask = np.ones(self.values.shape, dtype="uint8")
        mask[0, 0] = 0
        self.write(self.mask, mask, nodata=0, description="valid_pre_post")
        report = inspect_linear_inputs(self.pre, self.post, self.mask)
        self.assertEqual(report["counts"]["source_mask_restricted_pixels"], 1)
        inputs, _ = self.prepare()
        with rasterio.open(inputs.pre_event.path) as pre, rasterio.open(inputs.valid_mask) as valid:
            self.assertEqual(pre.read(1)[0, 0], DB_NODATA)
            self.assertEqual(int(valid.read(1).sum()), 5)

    def test_nonpositive_power_is_unknown_without_taking_logarithm(self):
        values = self.values.copy()
        values[0, 0], values[0, 1] = 0.0, -1.0
        self.write(self.pre, values)
        inputs, provenance = self.prepare()
        self.assertEqual(provenance["linear_input_check"]["counts"]["nonpositive_power_pixels"], 2)
        with rasterio.open(inputs.pre_event.path) as pre, rasterio.open(inputs.valid_mask) as valid:
            self.assertTrue(np.all(pre.read(1)[0, :2] == DB_NODATA))
            self.assertTrue(np.all(valid.read(1)[0, :2] == 0))
        self.assertEqual(check_analysis_inputs(inputs)["counts"]["joint_valid_pixels"], 4)

    def test_invalid_mask_and_source_conflict_are_rejected(self):
        values = self.values.copy()
        values[0, 0] = DB_NODATA
        self.write(self.pre, values)
        with self.assertRaises(R2Error) as found:
            inspect_linear_inputs(self.pre, self.post, self.mask)
        self.assertEqual(found.exception.code, "MASK_SOURCE_CONFLICT")
        invalid = np.ones(self.values.shape, dtype="uint8")
        invalid[0, 0] = 255
        self.write(self.mask, invalid, nodata=0, description="valid_pre_post")
        with self.assertRaises(R2Error) as found:
            inspect_linear_inputs(self.pre, self.post, self.mask)
        self.assertEqual(found.exception.code, "INVALID_MASK")

    def test_shifted_grid_and_geographic_units_are_rejected(self):
        self.write(self.post, self.values, transform=from_origin(500005, 4400000, 10, 10))
        with self.assertRaises(R2Error) as found:
            inspect_linear_inputs(self.pre, self.post, self.mask)
        self.assertEqual(found.exception.code, "GRID_MISMATCH")
        self.write(self.pre, self.values, crs="EPSG:4326")
        with self.assertRaises(R2Error) as found:
            inspect_linear_inputs(self.pre, self.post, self.mask)
        self.assertEqual(found.exception.code, "GRID_MISMATCH")

    def test_no_effective_observation_is_not_a_successful_empty_case(self):
        self.write(self.mask, np.zeros(self.values.shape, dtype="uint8"), nodata=0, description="valid_pre_post")
        with self.assertRaises(R2Error) as found:
            inspect_linear_inputs(self.pre, self.post, self.mask)
        self.assertEqual(found.exception.code, "NO_VALID_DATA")

    def test_known_db_values_tags_and_sources_are_preserved(self):
        before = {p.name: sha256_file(p) for p in (self.pre, self.post, self.mask)}
        expected = {"pre_event": before[self.pre.name], "post_event": before[self.post.name], "valid_mask": before[self.mask.name]}
        inputs, provenance = self.prepare(expected_hashes=expected)
        self.assertIsInstance(inputs, PreparedInputs)
        self.assertEqual(len(inputs.grid.transform), 6)
        self.assertIsNotNone(inputs.pre_event.acquired_at.tzinfo)
        with rasterio.open(inputs.pre_event.path) as ds:
            np.testing.assert_allclose(ds.read(1)[0], [-20, 0, 10], atol=1e-5)
            self.assertEqual(ds.tags()["backscatter_quantity"], "gamma0")
            self.assertEqual(ds.tags()["value_scale"], "db")
            self.assertEqual(ds.tags()["source_sha256"], before[self.pre.name])
            self.assertEqual(ds.dtypes, ("float32",))
        self.assertEqual(before, {p.name: sha256_file(p) for p in (self.pre, self.post, self.mask)})
        self.assertEqual(provenance["source_revision"], "synthetic_revision")
        encoded = json.loads((self.root / "derived" / "prepared_inputs.json").read_text(encoding="utf-8"))
        self.assertEqual(encoded["schema_version"], "2.0")
        self.assertEqual(encoded["pre_event"]["path"], "pre_event_db.tif")
        decoded = from_payload(PreparedInputs, encoded)
        self.assertEqual(decoded.grid, inputs.grid)
        self.assertEqual(check_analysis_inputs(inputs)["counts"]["joint_valid_pixels"], 6)

    def test_hash_mismatch_does_not_create_outputs(self):
        with self.assertRaises(R2Error) as found:
            self.prepare(expected_hashes={"pre_event": "0" * 64})
        self.assertEqual(found.exception.code, "INPUT_HASH_MISMATCH")
        self.assertFalse((self.root / "derived").exists())

    def test_missing_manifest_fields_and_naive_dates_are_rejected(self):
        self.payload["pre_event"].pop("source")
        self.save_manifest()
        with self.assertRaises(R2Error):
            self.prepare()
        self.payload = self.make_manifest()
        self.payload["pre_event"]["acquired_at"] = "2023-07-24T10:00:00"
        self.save_manifest()
        with self.assertRaises(R2Error):
            self.prepare()

    def test_manifest_nonaffine_ninth_row_and_wrong_dimensions_are_rejected(self):
        self.payload["grid"]["transform"][8] = 2
        self.save_manifest()
        with self.assertRaises(R2Error):
            self.prepare()
        self.payload = self.make_manifest()
        self.payload["grid"]["width"] = 4
        self.save_manifest()
        with self.assertRaises(R2Error) as found:
            self.prepare()
        self.assertEqual(found.exception.code, "GRID_MISMATCH")

    def test_no_overwrite_and_no_double_log_conversion(self):
        inputs, _ = self.prepare()
        with self.assertRaises(R2Error) as found:
            self.prepare()
        self.assertEqual(found.exception.code, "OUTPUT_EXISTS")
        with self.assertRaises(R2Error) as found:
            inspect_linear_inputs(inputs.pre_event.path, inputs.post_event.path, inputs.valid_mask)
        self.assertEqual(found.exception.code, "RADIOMETRY_UNDECLARED")
        with self.assertRaises(R2Error) as found:
            self.prepare(dirname=".")
        self.assertEqual(found.exception.code, "OUTPUT_EXISTS")

    def test_analysis_check_rejects_missing_tags_and_incorrect_declared_grid(self):
        inputs, _ = self.prepare()
        wrong_grid = replace(inputs, grid=replace(inputs.grid, width=4))
        with self.assertRaises(R2Error) as found:
            check_analysis_inputs(wrong_grid)
        self.assertEqual(found.exception.code, "GRID_MISMATCH")
        with rasterio.open(inputs.post_event.path, "r+") as ds:
            ds.update_tags(value_scale="linear_power")
        with self.assertRaises(R2Error) as found:
            check_analysis_inputs(inputs)
        self.assertEqual(found.exception.code, "RADIOMETRY_UNDECLARED")

    def test_analysis_check_rejects_mask_that_drops_derived_valid_pixels(self):
        inputs, _ = self.prepare()
        with rasterio.open(inputs.valid_mask, "r+") as ds:
            raw = ds.read(1)
            raw[0, 0] = 0
            ds.write(raw, 1)
        with self.assertRaises(R2Error) as found:
            check_analysis_inputs(inputs)
        self.assertEqual(found.exception.code, "MASK_SOURCE_CONFLICT")


if __name__ == "__main__":
    unittest.main()
