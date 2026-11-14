from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

try:
    import geopandas as gpd
    from shapely.geometry import LineString, Polygon
except ImportError:
    gpd = None

from remote_image.core.contracts import ContextLayers, ContextSources, SourceRecord, StudyArea
from remote_image.modules.decision.interfaces import validate_context_layers


@unittest.skipIf(gpd is None, "需要 GIS 可选依赖")
class Stage2R3Tests(unittest.TestCase):
    def setUp(self) -> None:
        temp_root = Path(__file__).resolve().parents[3] / "work" / "temp"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="r3-stage2-", dir=temp_root)
        self.root = Path(self.temp.name)
        self.buildings = self.root / "buildings.geojson"
        self.roads = self.root / "roads.geojson"
        gpd.GeoDataFrame({"building_id": ["b1"]}, geometry=[Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])],
                         crs="EPSG:3857").to_file(self.buildings, driver="GeoJSON")
        gpd.GeoDataFrame({"edge_id": ["e1"]}, geometry=[LineString([(0, 8), (10, 8)])],
                         crs="EPSG:3857").to_file(self.roads, driver="GeoJSON")
        observed = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.layers = ContextLayers(
            "case-a", "area-a", "EPSG:3857",
            {"buildings": self.buildings, "roads": self.roads},
            ContextSources("case-a", {
                "buildings": SourceRecord(self.buildings, "fixture buildings", observed, "CC0-1.0", "building_id"),
                "roads": SourceRecord(self.roads, "fixture roads", observed, "CC0-1.0", "edge_id"),
            }),
        )
        self.area = StudyArea("area-a", "POLYGON ((-1 -1, 11 -1, 11 11, -1 11, -1 -1))", "EPSG:3857")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_matching_event_and_area_pass_except_missing_population(self) -> None:
        report = validate_context_layers(self.layers, "case-a", area=self.area)
        self.assertEqual(report.status, "warning")
        self.assertFalse(any(check.status == "fail" for check in report.checks))
        self.assertTrue(any(check.name == "buildings.coverage" and check.status == "pass" for check in report.checks))
        self.assertEqual(report.metrics["buildings.feature_or_pixel_count"], 1)

    def test_no_area_does_not_claim_event_coverage(self) -> None:
        report = validate_context_layers(self.layers, "case-a")
        self.assertEqual(report.status, "warning")
        self.assertTrue(any(check.name == "event_coverage" and check.status == "warning" for check in report.checks))
        self.assertFalse(any(check.name.endswith(".coverage") for check in report.checks))

    def test_other_event_or_nonoverlapping_area_fails(self) -> None:
        other = validate_context_layers(self.layers, "xbd-event")
        self.assertEqual(other.status, "fail")
        self.assertTrue(any(check.name == "event_id" and check.status == "fail" for check in other.checks))
        remote = StudyArea("area-a", "POLYGON ((100 100, 110 100, 110 110, 100 110, 100 100))", "EPSG:3857")
        report = validate_context_layers(self.layers, "case-a", area=remote)
        self.assertEqual(report.status, "fail")
        self.assertTrue(any(check.name == "buildings.coverage" and check.status == "fail" for check in report.checks))

    def test_unknown_date_and_duplicate_ids_are_reported(self) -> None:
        frame = gpd.read_file(self.buildings)
        frame = gpd.GeoDataFrame([frame.iloc[0], frame.iloc[0]], crs=frame.crs)
        frame.to_file(self.buildings, driver="GeoJSON")
        sources = dict(self.layers.sources.layers)
        sources["buildings"] = replace(sources["buildings"], date=None)
        layers = replace(self.layers, sources=ContextSources("case-a", sources))
        report = validate_context_layers(layers, "case-a", area=self.area)
        self.assertEqual(report.status, "fail")
        self.assertTrue(any(check.name == "buildings.date" and check.status == "warning" for check in report.checks))
        self.assertTrue(any(check.name == "buildings.object_ids" and check.status == "fail" for check in report.checks))

    def test_legacy_stage1_signature_remains_available(self) -> None:
        report = validate_context_layers(self.layers, self.area)
        self.assertNotEqual(report.status, "fail")


if __name__ == "__main__":
    unittest.main()
