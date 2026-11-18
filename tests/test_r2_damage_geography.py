"""第二阶段空间 QA 的正常、偏移、重复和空结果案例。"""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

from remote_image.core.contracts import DamageResult, ResultMeta
from remote_image.core.serialization import to_payload
from remote_image.modules.flood.interfaces import check_damage_geography


class DamageGeographyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.buildings = self.root / "buildings.gpkg"
        self.tiles = self.root / "tiles.gpkg"
        self.damage = self.root / "damage.gpkg"
        self._write(self.buildings, [{"building_id": "b1", "geometry": box(10, 10, 20, 20)}])
        self._write(self.tiles, [{"tile_id": "t1", "event_id": "case", "study_area_id": "area", "geometry": box(0, 0, 100, 100)}])
        self.meta = ResultMeta(schema_version="2.0", event_id="case", study_area_id="area", input_asset_ids=("pre", "post"),
                               method="building_damage", method_version="1", created_at=datetime.now(timezone.utc))
        (self.root / "metadata.json").write_text(json.dumps(to_payload(self.meta)), encoding="utf-8")

    @staticmethod
    def _write(path, rows):
        gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:32650").to_file(path, driver="GPKG")

    def _result(self, rows):
        self._write(self.damage, rows)
        return DamageResult(artifacts={"damage_vector": self.damage, "tile_index": self.tiles, "metadata": self.root / "metadata.json"},
                            model_name="model", model_version="1", meta=self.meta)

    @staticmethod
    def _row(bid="b1", geom=None):
        return {"building_id": bid, "event_id": "case", "study_area_id": "area", "model_name": "model", "model_version": "1",
                "damage_class": "minor-damage", "confidence": 0.8, "reason": None, "geometry": geom or box(10, 10, 20, 20)}

    def test_matching_building_passes_and_writes_report(self):
        report = check_damage_geography(self._result([self._row()]), self.buildings, self.tiles, "EPSG:32650", 1, self.root / "qa")
        self.assertEqual(report.status, "pass")
        self.assertEqual(report.metrics["issue_count"], 0)
        payload = json.loads((self.root / "qa" / "spatial_qa.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "pass")

    def test_offset_and_duplicate_id_fail_with_inspectable_rows(self):
        report = check_damage_geography(self._result([self._row(geom=box(50, 50, 60, 60)), self._row()]),
                                        self.buildings, self.tiles, "EPSG:32650", 1, self.root / "qa")
        self.assertEqual(report.status, "fail")
        self.assertEqual(report.metrics["issue_counts"]["damage_duplicate_id"], 2)
        self.assertEqual(report.metrics["issue_counts"]["building_offset"], 1)
        self.assertTrue(report.artifacts["suspect_samples"].is_file())

    def test_crs_mismatch_and_unsafe_tolerance_rejected(self):
        result = self._result([self._row()])
        with self.assertRaisesRegex(ValueError, "CRS"):
            check_damage_geography(result, self.buildings, self.tiles, "EPSG:3857", 1, self.root / "qa")
        with self.assertRaisesRegex(ValueError, "match_tolerance"):
            check_damage_geography(result, self.buildings, self.tiles, "EPSG:32650", -1, self.root / "qa")

    def test_missing_building_and_tile_boundary_are_reported(self):
        report = check_damage_geography(self._result([self._row("unknown", box(99, 10, 102, 20))]),
                                        self.buildings, self.tiles, "EPSG:32650", 0, self.root / "qa")
        self.assertEqual(report.status, "fail")
        self.assertEqual(report.metrics["issue_counts"]["building_not_found"], 1)
        self.assertEqual(report.metrics["issue_counts"]["outside_tiles"], 1)

    def test_wrong_model_and_invalid_confidence_fail(self):
        row = self._row()
        row["model_version"] = "other"
        row["confidence"] = 1.5
        report = check_damage_geography(self._result([row]), self.buildings, self.tiles, "EPSG:32650", 1, self.root / "qa")
        self.assertEqual(report.metrics["issue_counts"]["model_mismatch"], 1)
        self.assertEqual(report.metrics["issue_counts"]["invalid_prediction"], 1)

    def test_empty_baseline_is_warning_not_success(self):
        self._write(self.damage, [self._row()])
        frame = gpd.read_file(self.damage).iloc[:0]
        frame.to_file(self.damage, driver="GPKG")
        result = DamageResult(artifacts={"damage_vector": self.damage, "tile_index": self.tiles, "metadata": self.root / "metadata.json"},
                              model_name="model", model_version="1", meta=self.meta)
        report = check_damage_geography(result, self.buildings, self.tiles, "EPSG:32650", 1, self.root / "qa")
        self.assertEqual(report.status, "warning")
        self.assertEqual(report.metrics["damage_count"], 0)


if __name__ == "__main__":
    unittest.main()
