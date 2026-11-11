"""用合成像元和几何核对暴露统计，不作为真实灾区精度证据。"""
from __future__ import annotations

import csv
import gc
import time
import tempfile
import unittest
import warnings
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import rasterio
from rasterio.features import shapes
from rasterio.transform import from_origin
from shapely.geometry import LineString, Polygon, box, shape

from remote_image.core.contracts import (
    ContextLayers, ContextSources, ExposureReport, FloodResult, ResultMeta, SourceRecord,
)
from remote_image.core.serialization import from_payload, to_payload
from remote_image.modules.flood.exposure import summarize_exposure
from remote_image.modules.flood.qa import R2Error, write_json

CRS = "EPSG:32650"
X, Y = 500000.0, 4400000.0
WORK = Path(__file__).resolve().parents[1] / "work" / "temp"


def rectangle(x1, y1, x2, y2):
    return box(X + x1, Y + y1, X + x2, Y + y2)


def line(points):
    return LineString([(X + x, Y + y) for x, y in points])


class ExposureTests(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=WORK)
        self.root = Path(self.directory.name)
        self.event_id = "synthetic_exposure"
        self.meta = ResultMeta("2.0", self.event_id, "synthetic_area", ("synthetic_pre", "synthetic_post"), "sar_post_threshold", "test")
        self.paths = {}
        self.sources = {}

    def tearDown(self):
        self.assertTrue(self.root.resolve().is_relative_to(WORK.resolve()))
        for attempt in range(3):
            try:
                self.directory.cleanup()
                break
            except OSError:
                if attempt == 2:
                    raise
                gc.collect()
                time.sleep(0.1)

    def flood(self, mask, duplicate_polygons=False):
        mask = np.asarray(mask, dtype="uint8")
        transform = from_origin(X, Y + mask.shape[0] * 10, 10, 10)
        mask_path = self.root / "flood_mask.tif"
        with rasterio.open(mask_path, "w", driver="GTiff", height=mask.shape[0], width=mask.shape[1], count=1,
                           dtype="uint8", crs=CRS, transform=transform, nodata=255) as dst:
            dst.write(mask, 1)
        geometries = [shape(geom) for geom, value in shapes(mask, mask=mask == 1, transform=transform)]
        if duplicate_polygons:
            geometries += geometries
        vector_path = self.root / "flood_polygons.gpkg"
        frame = gpd.GeoDataFrame({"event_id": [self.event_id] * len(geometries)}, geometry=geometries, crs=CRS)
        pyogrio.write_dataframe(frame, vector_path, layer="flood_polygons", driver="GPKG", geometry_type="MultiPolygon", promote_to_multi=True)
        metadata = self.root / "metadata.json"
        write_json(metadata, self.meta)
        return FloodResult({"flood_mask": mask_path, "flood_polygons": vector_path, "metadata": metadata}, self.meta)

    def add_layer(self, kind, ids, geometries, crs=CRS):
        path = self.root / f"{kind}.gpkg"
        frame = gpd.GeoDataFrame({"id": ids}, geometry=geometries, crs=crs)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pyogrio.write_dataframe(frame, path, driver="GPKG")
        self.paths[kind] = path
        self.sources[kind] = SourceRecord(path, "synthetic_fixture", None, "CC0-test", "id")
        return path

    def context(self):
        return ContextLayers(self.event_id, self.meta.study_area_id, CRS, self.paths,
                             ContextSources(self.event_id, self.sources))

    def records(self, kind):
        frame = gpd.read_file(self.root / "exposure_features.gpkg", layer=kind)
        return {row.source_id: row for _, row in frame.iterrows()}

    def test_multi_face_exact_intersection_deduplicates_and_preserves_ids(self):
        flood = self.flood([[1, 0, 0], [0, 0, 0], [1, 0, 0]], duplicate_polygons=True)
        building = rectangle(0, 0, 20, 30)
        self.add_layer("buildings", ["way:1", "way:1", "relation:1"],
                       [building, building, rectangle(20, 0, 30, 10)])
        report = summarize_exposure(flood, self.context(), CRS)
        self.assertEqual(report.metrics["building_objects_intersecting"], 1)
        self.assertAlmostEqual(report.metrics["building_overlap_area_m2"], 200)
        self.assertEqual(report.metrics["building_objects_total"], 2)
        records = self.records("buildings")
        self.assertEqual(set(records), {"way:1", "relation:1"})
        self.assertAlmostEqual(records["way:1"].overlap_fraction_of_total, 1 / 3)
        self.assertEqual(records["way:1"].observed_status, "complete")
        self.assertTrue(bool(records["way:1"].candidate_exposed))
        self.assertEqual(len(gpd.read_file(report.affected_features_path, layer="roads")), 0)

    def test_unknown_partial_coverage_and_boundary_contact(self):
        flood = self.flood([[1, 0, 0, 255], [1, 0, 0, 255], [0, 0, 0, 255], [0, 0, 0, 255]])
        self.add_layer("buildings", ["outside", "partial_zero", "partial_hit", "touch", "full_hit"],
                       [rectangle(50, 0, 60, 10), rectangle(20, 0, 40, 10), rectangle(0, 20, 40, 30),
                        rectangle(10, 30, 20, 40), rectangle(0, 20, 10, 40)])
        report = summarize_exposure(flood, self.context(), CRS)
        r = self.records("buildings")
        self.assertEqual(r["outside"].observed_status, "unobserved")
        self.assertTrue(pd.isna(r["outside"].candidate_overlap_m2))
        self.assertTrue(pd.isna(r["outside"].candidate_exposed))
        self.assertEqual(r["outside"].outside_raster_area_m2, 100)
        self.assertEqual(r["outside"].unknown_within_raster_area_m2, 0)
        self.assertEqual(r["partial_zero"].observed_status, "partial")
        self.assertEqual(r["partial_zero"].candidate_overlap_m2, 0)
        self.assertEqual(r["partial_zero"].unknown_within_raster_area_m2, 100)
        self.assertEqual(r["partial_zero"].outside_raster_area_m2, 0)
        self.assertTrue(pd.isna(r["partial_zero"].candidate_exposed))
        self.assertTrue(pd.isna(r["partial_zero"].overlap_fraction_of_total))
        self.assertTrue(bool(r["partial_hit"].candidate_exposed))
        self.assertTrue(pd.isna(r["partial_hit"].overlap_fraction_of_total))
        self.assertAlmostEqual(r["partial_hit"].candidate_overlap_m2, 100)
        self.assertFalse(bool(r["touch"].candidate_exposed))
        self.assertEqual(r["touch"].candidate_overlap_m2, 0)
        self.assertEqual(report.metrics["building_objects_intersecting"], 2)
        self.assertEqual(report.metrics["building_objects_unknown"], 2)
        self.assertAlmostEqual(report.metrics["observed_area_m2"], 1200)
        self.assertAlmostEqual(report.metrics["unknown_area_m2"], 400)

    def test_road_exact_length_multi_hits_point_touch_and_unknown(self):
        flood = self.flood([[1, 0, 0], [0, 0, 0], [1, 0, 0]])
        self.add_layer("roads", ["road:cross", "road:point", "road:outside"],
                       [line([(5, 0), (5, 30)]), line([(10, 30), (20, 30)]), line([(40, 0), (40, 30)])])
        report = summarize_exposure(flood, self.context(), CRS)
        r = self.records("roads")
        self.assertAlmostEqual(report.metrics["road_overlap_length_m"], 20)
        self.assertAlmostEqual(r["road:cross"].candidate_overlap_length_m, 20)
        self.assertEqual(r["road:point"].candidate_overlap_length_m, 0)
        self.assertTrue(pd.isna(r["road:outside"].candidate_overlap_length_m))
        self.assertNotIn("blocked", r["road:cross"].index)
        self.assertIsNone(report.metrics["building_objects_intersecting"])
        self.assertIsNone(report.metrics["population_exposed"])

    def test_all_source_objects_unobserved_overlap_is_null(self):
        flood = self.flood([[0, 0], [0, 0]])
        self.add_layer("buildings", ["outside"], [rectangle(40, 0, 50, 10)])
        self.add_layer("roads", ["outside"], [line([(40, 0), (40, 20)])])
        report = summarize_exposure(flood, self.context(), CRS)
        self.assertIsNone(report.metrics["building_overlap_area_m2"])
        self.assertIsNone(report.metrics["road_overlap_length_m"])
        self.assertEqual(report.metrics["building_objects_unknown"], 1)

    def test_duplicate_id_conflicting_geometry_rejected(self):
        flood = self.flood([[1, 0], [0, 0]])
        self.add_layer("buildings", ["way:1", "way:1"], [rectangle(0, 0, 10, 10), rectangle(10, 0, 20, 10)])
        with self.assertRaises(R2Error) as captured:
            summarize_exposure(flood, self.context(), CRS)
        self.assertEqual(captured.exception.code, "DUPLICATE_ID_CONFLICT")

    def test_invalid_and_missing_geometry_are_reported(self):
        flood = self.flood([[1, 0], [0, 0]])
        bowtie = Polygon([(X, Y), (X + 10, Y + 10), (X, Y + 10), (X + 10, Y), (X, Y)])
        self.add_layer("buildings", ["missing", "invalid", "valid"], [None, bowtie, rectangle(0, 0, 10, 10)])
        report = summarize_exposure(flood, self.context(), CRS)
        self.assertEqual(report.metrics["building_objects_invalid"], 2)
        self.assertEqual(report.metrics["building_objects_unknown"], 2)
        with (self.root / "exposure_geometry_issues.csv").open(encoding="utf-8", newline="") as stream:
            issues = list(csv.DictReader(stream))
        self.assertEqual(len(issues), 2)
        self.assertTrue(any("invalid_geometry" in row["reason"] for row in issues))
        self.assertTrue(any(row["reason"] == "missing_geometry" for row in issues))

    def test_empty_candidates_is_known_zero_and_outputs_reopen(self):
        flood = self.flood([[0, 0], [0, 0]])
        self.add_layer("buildings", ["known"], [rectangle(0, 0, 10, 10)])
        self.add_layer("roads", [], [])
        report = summarize_exposure(flood, self.context(), CRS)
        self.assertEqual(report.metrics["candidate_area_m2"], 0)
        self.assertEqual(report.metrics["building_objects_intersecting"], 0)
        self.assertEqual(report.metrics["building_overlap_area_m2"], 0)
        self.assertEqual(report.metrics["road_overlap_length_m"], 0)
        self.assertEqual(len(gpd.read_file(report.affected_features_path, layer="roads")), 0)
        self.assertFalse(bool(self.records("buildings")["known"].candidate_exposed))
        self.assertTrue((self.root / "exposure_report.json").is_file())
        self.assertTrue(report.statistics_path.is_file())

    def test_missing_layers_remain_null_in_report_and_csv(self):
        flood = self.flood([[0, 0], [0, 0]])
        report = summarize_exposure(flood, self.context(), CRS)
        for key in ["building_objects_intersecting", "building_overlap_area_m2", "road_overlap_length_m", "population_exposed"]:
            self.assertIsNone(report.metrics[key])
        with report.statistics_path.open(encoding="utf-8", newline="") as stream:
            rows = {row["metric"]: row for row in csv.DictReader(stream)}
        self.assertEqual(rows["road_overlap_length_m"]["value"], "")

    def test_missing_crs_and_wrong_event_rejected(self):
        flood = self.flood([[0, 0], [0, 0]])
        self.add_layer("buildings", ["way:1"], [rectangle(0, 0, 10, 10)], crs=None)
        with self.assertRaises(R2Error) as captured:
            summarize_exposure(flood, self.context(), CRS)
        self.assertEqual(captured.exception.code, "MISSING_CRS")
        with self.assertRaises(R2Error) as captured:
            summarize_exposure(flood, replace(self.context(), event_id="another_event"), CRS)
        self.assertEqual(captured.exception.code, "EVENT_MISMATCH")

    def test_geographic_source_is_projected_before_area_intersection(self):
        flood = self.flood([[1, 0], [0, 0]])
        geographic = gpd.GeoSeries([rectangle(0, 0, 20, 20)], crs=CRS).to_crs("EPSG:4326")
        self.add_layer("buildings", ["way:9"], list(geographic), crs="EPSG:4326")
        report = summarize_exposure(flood, self.context(), CRS)
        self.assertAlmostEqual(report.metrics["building_overlap_area_m2"], 100, places=4)
        self.assertAlmostEqual(self.records("buildings")["way:9"].building_area_m2, 400, places=4)

    def test_dated_source_metadata_survives_contract_roundtrip(self):
        flood = self.flood([[0, 0], [0, 0]])
        self.add_layer("buildings", ["way:date"], [rectangle(0, 0, 10, 10)])
        self.sources["buildings"] = replace(self.sources["buildings"], date=datetime(2023, 7, 23, tzinfo=timezone.utc))
        report = summarize_exposure(flood, self.context(), CRS)
        self.assertEqual(from_payload(ExposureReport, to_payload(report)), report)

    def test_geographic_analysis_crs_rejected(self):
        flood = self.flood([[0, 0], [0, 0]])
        with self.assertRaises(R2Error) as captured:
            summarize_exposure(flood, self.context(), "EPSG:4326")
        self.assertEqual(captured.exception.code, "INVALID_CRS")


if __name__ == "__main__":
    unittest.main()
