"""用合成空间数据检查 R2 四个公开入口的完整交接，不代表真实灾区精度。"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import time
import unittest

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, box

from remote_image.core.contracts import (
    ContextLayers, ContextSources, ExposureReport, FloodContext, FloodOptions,
    FloodRequest, FloodResult, SourceRecord, StudyArea, ThresholdReport,
)
from remote_image.core.serialization import from_payload, to_payload
from remote_image.core.validation import validate_contract
from remote_image.modules.flood import interfaces
from remote_image.modules.flood.input_io import DB_NODATA, prepare_analysis_inputs
from remote_image.modules.flood.qa import R2Error, check_flood_artifacts
from remote_image.modules.flood.thresholds import evaluate_candidates
from remote_image.modules.flood.vectorization import verify_vector_mask

ROOT = Path(__file__).resolve().parents[1]


class R2PipelineTests(unittest.TestCase):
    def setUp(self):
        work = ROOT / "work"
        work.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=work, prefix="r2-pipeline-test-")
        self.addCleanup(self.cleanup_temp)
        self.root = Path(self.temp.name)
        self.transform = from_origin(500000, 4400000, 10, 10)
        self.pre_values = np.full((6, 6), 0.1, dtype="float32")
        self.post_values = self.pre_values.copy()
        # 已有水体不计为新增；中间四个像元为合成新增候选。
        self.pre_values[0, 0] = self.post_values[0, 0] = 0.001
        self.post_values[1:3, 1:3] = 0.001
        self.mask_values = np.ones((6, 6), dtype="uint8")
        self.mask_values[5, 5] = 0
        self.inputs = self.make_inputs(self.pre_values, self.post_values, self.mask_values)
        self.options = self.option(-20)
        boundary = self.root / "study_area.geojson"
        gpd.GeoDataFrame({"name": ["synthetic_extent"]}, geometry=[box(500000, 4399940, 500060, 4400000)], crs="EPSG:32650").to_crs("EPSG:4326").to_file(boundary, driver="GeoJSON", engine="pyogrio")
        self.area = StudyArea("synthetic_area", str(boundary), "EPSG:4326")

    def cleanup_temp(self):
        for attempt in range(4):
            try:
                self.temp.cleanup()
                return
            except OSError as error:
                if attempt == 3 or getattr(error, "winerror", None) not in (32, 145):
                    raise
                time.sleep(0.1)

    def write_raster(self, path, values, *, nodata=DB_NODATA, description="VV", tags=None):
        with rasterio.open(path, "w", driver="GTiff", height=6, width=6, count=1, dtype=values.dtype, crs="EPSG:32650", transform=self.transform, nodata=nodata) as ds:
            ds.write(values, 1)
            ds.set_band_description(1, description)
            if tags:
                ds.update_tags(**tags)

    def make_inputs(self, pre_values, post_values, mask_values, name="main"):
        source = self.root / ("r1_" + name)
        source.mkdir()
        pre, post, mask = (source / filename for filename in ("pre.tif", "post.tif", "mask.tif"))
        self.write_raster(pre, pre_values)
        self.write_raster(post, post_values)
        self.write_raster(mask, mask_values, nodata=0, description="valid_pre_post")
        assets = []
        for kind, date in (("pre", "2023-07-24T10:00:00Z"), ("post", "2023-08-05T10:00:00Z")):
            assets.append({"asset_id": f"synthetic_{name}_{kind}", "path": kind + ".tif", "acquired_at": date,
                           "source": "synthetic gamma0 fixture", "coordinate_reference_system": "EPSG:32650",
                           "pixel_size_m": 10.0, "bands": ["VV"], "footprint": None,
                           "source_type": "satellite", "is_substitute": False, "quality_notes": "synthetic",
                           "width": 6, "height": 6, "count": 1, "transform": list(self.transform)})
        payload = {"pre_event": assets[0], "post_event": assets[1], "study_area_id": "synthetic_area",
                   "grid": {"transform": list(self.transform), "width": 6, "height": 6,
                            "pixel_size_x_m": 10.0, "pixel_size_y_m": 10.0}, "valid_mask": "mask.tif"}
        manifest = source / "prepared_inputs.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        inputs, _ = prepare_analysis_inputs(manifest, pre, post, mask, self.root / ("analysis_" + name), source_revision="synthetic_revision")
        return inputs

    @staticmethod
    def option(threshold, minimum=0):
        return FloodOptions(polarizations=("VV",), post_thresholds_db={"VV": threshold},
                            pre_water_thresholds_db={"VV": threshold}, polarization_rule="single",
                            min_patch_area_m2=minimum)

    def request(self, inputs=None, output="run"):
        return FloodRequest("synthetic_event", self.area, inputs or self.inputs, self.options, self.root / output)

    def context(self):
        buildings = self.root / "buildings.gpkg"
        roads = self.root / "roads.gpkg"
        gpd.GeoDataFrame({"source_id": ["building_inside", "building_outside"]},
                         geometry=[box(500012, 4399982, 500018, 4399988), box(500042, 4399952, 500048, 4399958)],
                         crs="EPSG:32650").to_file(buildings, driver="GPKG", engine="pyogrio")
        gpd.GeoDataFrame({"source_id": ["road_crossing"]},
                         geometry=[LineString([(500000, 4399985), (500040, 4399985)])],
                         crs="EPSG:32650").to_file(roads, driver="GPKG", engine="pyogrio")
        files = {"buildings": buildings, "roads": roads}
        sources = ContextSources("synthetic_event", {key: SourceRecord(path, "synthetic_fixture", datetime(2023, 8, 5, tzinfo=timezone.utc), "test-only", "source_id") for key, path in files.items()})
        return ContextLayers("synthetic_event", "synthetic_area", "EPSG:32650", files, sources)

    def test_four_public_interfaces_produce_valid_roundtrippable_artifacts(self):
        thresholds = interfaces.evaluate_flood_thresholds(self.inputs, [self.options], None, self.root / "evaluation")
        validate_contract(thresholds)
        self.assertEqual(from_payload(ThresholdReport, to_payload(thresholds)), thresholds)
        flood = interfaces.run_flood_baseline(self.request())
        validate_contract(flood)
        self.assertEqual(from_payload(FloodResult, to_payload(flood)), flood)
        self.assertTrue({"flood_mask", "flood_polygons", "metadata"} <= flood.artifacts.keys())
        self.assertTrue(all(Path(path).is_file() for path in flood.artifacts.values()))
        self.assertEqual(check_flood_artifacts(flood)["status"], "pass")
        with rasterio.open(flood.artifacts["flood_mask"]) as ds:
            mask = ds.read(1)
            self.assertEqual(ds.nodata, 255)
            self.assertEqual(ds.dtypes[0], "uint8")
        self.assertEqual(int((mask == 1).sum()), 4)
        self.assertEqual(int((mask == 255).sum()), 1)
        self.assertEqual(mask[0, 0], 0)
        ctx = FloodContext(flood.meta.event_id, flood.meta.study_area_id, flood.meta.method,
                           flood.meta.method_version, flood.meta.parameters, "EPSG:32650")
        duplicate = interfaces.polygonize_mask(flood.artifacts["flood_mask"], ctx, self.root / "independent_polygons.gpkg")
        self.assertEqual(verify_vector_mask(flood.artifacts["flood_mask"], duplicate)["mismatch_pixels"], 0)
        exposure = interfaces.summarize_exposure(flood, self.context(), "EPSG:32650")
        validate_contract(exposure)
        self.assertEqual(from_payload(ExposureReport, to_payload(exposure)), exposure)
        self.assertAlmostEqual(exposure.metrics["candidate_area_m2"], 400.0)
        self.assertAlmostEqual(exposure.metrics["observed_area_m2"], 3500.0)
        self.assertAlmostEqual(exposure.metrics["unknown_area_m2"], 100.0)
        self.assertEqual(exposure.metrics["building_objects_intersecting"], 1)
        self.assertAlmostEqual(exposure.metrics["building_overlap_area_m2"], 36.0)
        self.assertAlmostEqual(exposure.metrics["road_overlap_length_m"], 20.0)
        self.assertIsNone(exposure.metrics["population_exposed"])
        self.assertTrue(exposure.statistics_path.is_file())
        self.assertTrue(exposure.affected_features_path.is_file())
        self.assertTrue(gpd.read_file(flood.artifacts["flood_polygons_geojson"]).crs.is_geographic)

    def test_no_reference_report_retains_null_accuracy_and_explicit_trial_choice(self):
        candidates = [self.option(-22), self.option(-18)]
        report = interfaces.evaluate_flood_thresholds(self.inputs, candidates, None, self.root / "no_reference")
        self.assertFalse(report.reference_available)
        self.assertEqual(report.status, "warning")
        self.assertEqual(report.selected_options, candidates[0])
        self.assertEqual(report.metrics["selected_index"], 0)
        for metric in ("precision", "recall", "f1", "iou"):
            self.assertIsNone(report.metrics[metric])
            self.assertTrue(all(row[metric] is None for row in report.metrics["candidates"]))
        self.assertTrue(report.selection_reason)
        self.assertTrue(report.warnings)
        self.assertTrue((self.root / "no_reference" / "selected_options.json").is_file())

    def test_empty_candidate_list_is_rejected(self):
        with self.assertRaises(R2Error) as found:
            interfaces.evaluate_flood_thresholds(self.inputs, [], None, self.root / "empty_candidates")
        self.assertEqual(found.exception.code, "EMPTY_CANDIDATES")

    def test_identical_inputs_create_real_empty_layers_instead_of_missing_files(self):
        identical = self.make_inputs(self.pre_values, self.pre_values, self.mask_values, "identical")
        result = interfaces.run_flood_baseline(self.request(identical, "identical_run"))
        self.assertEqual(check_flood_artifacts(result)["status"], "pass")
        with rasterio.open(result.artifacts["flood_mask"]) as ds:
            raw = ds.read(1)
        self.assertEqual(int((raw == 1).sum()), 0)
        self.assertEqual(int((raw == 0).sum()), 35)
        self.assertEqual(int((raw == 255).sum()), 1)
        frame = gpd.read_file(result.artifacts["flood_polygons"], layer="flood_polygons")
        self.assertTrue(frame.empty)
        self.assertIsNotNone(frame.crs)
        self.assertTrue(gpd.read_file(result.artifacts["flood_polygons_geojson"]).empty)
        self.assertEqual(verify_vector_mask(result.artifacts["flood_mask"], result.artifacts["flood_polygons"])["mismatch_pixels"], 0)

    def test_all_unknown_analysis_inputs_fail_without_claiming_zero_candidates(self):
        for asset in (self.inputs.pre_event, self.inputs.post_event):
            with rasterio.open(asset.path, "r+") as ds:
                ds.write(np.full((6, 6), DB_NODATA, dtype="float32"), 1)
        with rasterio.open(self.inputs.valid_mask, "r+") as ds:
            ds.write(np.zeros((6, 6), dtype="uint8"), 1)
        with self.assertRaises(R2Error) as found:
            interfaces.run_flood_baseline(self.request(output="all_unknown"))
        self.assertEqual(found.exception.code, "NO_VALID_DATA")
        self.assertFalse((self.root / "all_unknown" / "flood_result.json").exists())

    def test_missing_artifact_key_and_nonexistent_artifact_file_fail_handoff(self):
        result = interfaces.run_flood_baseline(self.request(output="artifact_checks"))
        missing_key = replace(result, artifacts={key: path for key, path in result.artifacts.items() if key != "metadata"})
        with self.assertRaises(R2Error) as found:
            check_flood_artifacts(missing_key)
        self.assertEqual(found.exception.code, "MISSING_ARTIFACT")
        missing_file = replace(result, artifacts={**result.artifacts, "metadata": self.root / "absent.json"})
        with self.assertRaises(R2Error) as found:
            check_flood_artifacts(missing_file)
        self.assertEqual(found.exception.code, "MISSING_ARTIFACT")

    def test_threshold_cleanup_uses_full_components_before_development_scoring(self):
        pre = np.full((6, 6), 0.1, dtype="float32")
        post = pre.copy()
        post[2, 1:5] = 0.001
        inputs = self.make_inputs(pre, post, np.ones((6, 6), dtype="uint8"), "boundary")
        development = np.zeros((6, 6), dtype=bool)
        development[2, 1] = True
        reference = self.root / "synthetic_reference.tif"
        labels = np.zeros((6, 6), dtype="uint8")
        labels[2, 1:5] = 1
        self.write_raster(reference, labels, nodata=255, description="synthetic_new_flood", tags={
            "target": "new_flood", "pre_event_date": "2023-07-24", "post_event_date": "2023-08-05"})
        report = evaluate_candidates(inputs, [self.option(-20, minimum=300)], reference,
                                     self.root / "boundary_evaluation", development_mask=development)
        row = report.metrics["candidates"][0]
        # 四像元的完整连通域达到 300m²；开发区仅包含其中一个像元。
        self.assertEqual(row["candidate_pixels"], 1)
        self.assertEqual(row["candidate_area_m2"], 100.0)
        self.assertEqual(row["components_intersecting_development"], 1)
        self.assertEqual(row["tp"], 1)
        self.assertEqual(row["evaluated_pixels"], 1)
        self.assertEqual(report.metrics["f1"], 1.0)
        self.assertTrue(report.reference_available)
        with rasterio.open(report.artifacts["candidate_0"]) as ds:
            self.assertEqual(int((ds.read(1) == 1).sum()), 4)

    def test_reference_target_mismatch_is_rejected_before_selecting_parameters(self):
        reference = self.root / "wrong_target.tif"
        self.write_raster(reference, np.zeros((6, 6), dtype="uint8"), nodata=255,
                          description="synthetic_water", tags={"target": "all_water"})
        with self.assertRaises(R2Error) as found:
            evaluate_candidates(self.inputs, [self.options], reference, self.root / "wrong_reference")
        self.assertEqual(found.exception.code, "REFERENCE_TARGET_MISMATCH")


    def test_candidates_with_different_auxiliary_mask_content_are_rejected(self):
        first = self.root / "exclusion_a.tif"
        second = self.root / "exclusion_b.tif"
        a = np.zeros((6, 6), dtype="uint8")
        b = a.copy()
        b[1, 1] = 1
        self.write_raster(first, a, nodata=255, description="synthetic_exclusion")
        self.write_raster(second, b, nodata=255, description="synthetic_exclusion")
        candidates = [replace(self.options, exclusion_mask=first),
                      replace(self.options, exclusion_mask=second)]
        with self.assertRaises(R2Error) as found:
            interfaces.evaluate_flood_thresholds(self.inputs, candidates, None,
                                                self.root / "incomparable_candidates")
        self.assertEqual(found.exception.code, "INCOMPARABLE_CANDIDATES")

    def test_zero_reference_and_zero_predictions_do_not_claim_maximum_f1(self):
        reference = self.root / "synthetic_zero_reference.tif"
        self.write_raster(reference, np.zeros((6, 6), dtype="uint8"), nodata=255,
                          description="synthetic_new_flood", tags={
                              "target": "new_flood", "pre_event_date": "2023-07-24",
                              "post_event_date": "2023-08-05"})
        # 所有有效值均高于这两个阈值，因此预测与参考都没有正类。
        report = interfaces.evaluate_flood_thresholds(
            self.inputs, [self.option(-100), self.option(-90)], reference,
            self.root / "undefined_f1")
        self.assertTrue(report.reference_available)
        self.assertEqual(report.status, "warning")
        self.assertIsNone(report.metrics["f1"])
        self.assertTrue(all(row["f1"] is None for row in report.metrics["candidates"]))
        self.assertTrue(all(row["candidate_pixels"] == 0 for row in report.metrics["candidates"]))
        self.assertIn("无定义", report.selection_reason)
        self.assertNotIn("F1 最大值", report.selection_reason)
        self.assertTrue(report.warnings)

    def test_public_evaluation_does_not_claim_an_unprovided_heldout_split(self):
        reference = self.root / "synthetic_positive_reference.tif"
        labels = np.zeros((6, 6), dtype="uint8")
        labels[1:3, 1:3] = 1
        self.write_raster(reference, labels, nodata=255, description="synthetic_new_flood", tags={
            "target": "new_flood", "pre_event_date": "2023-07-24", "post_event_date": "2023-08-05"})
        # 公共签名没有开发区/留出区参数，此处也没有提供隔离证据。
        report = interfaces.evaluate_flood_thresholds(
            self.inputs, [self.options], reference, self.root / "public_evaluation")
        self.assertEqual(report.metrics["f1"], 1.0)
        self.assertNotIn("测试区未参与", report.selection_reason)
        self.assertEqual(report.status, "warning")


if __name__ == "__main__":
    unittest.main()
