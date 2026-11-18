"""Run the pinned R2 implementation and consume its actual artifacts in C3."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

from remote_image.core.contracts import DamageResult, ResultMeta
from remote_image.core.serialization import from_payload, to_payload
from remote_image.modules.flood.interfaces import check_damage_geography
from remote_image.modules.visualization.stage1 import VisualizationInputError, render_map
from remote_image.modules.visualization.stage2 import load_damage_result
from remote_image.modules.visualization.spatial_qa import load_spatial_qa_view

ROOT = Path(__file__).resolve().parents[3]


class R2C3IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r2-c3-", dir=ROOT / "work")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def prepare(self, mode="pass"):
        def write(name, rows):
            path = self.root / name
            gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:32650").to_file(path, driver="GPKG")
            return path
        source = write("buildings.gpkg", [{"building_id": "b1", "geometry": box(10, 10, 20, 20)}])
        tiles = write("tiles.gpkg", [{"tile_id": "t1", "event_id": "r2-case", "study_area_id": "area",
            "geometry": box(10 if mode == "warning" else 0, 0, 100, 100)}])
        damage = write("damage.gpkg", [{"building_id": "b1", "event_id": "r2-case", "study_area_id": "area",
            "model_name": "test-model", "model_version": "1", "damage_class": "minor-damage",
            "confidence": .8, "reason": None,
            "geometry": box(50, 50, 60, 60) if mode == "fail" else box(10, 10, 20, 20)}])
        meta = ResultMeta(schema_version="2.0", event_id="r2-case", study_area_id="area",
            input_asset_ids=("pre", "post"), method="building_damage", method_version="1",
            created_at=datetime.now(timezone.utc))
        metadata = self.root / "metadata.json"
        metadata.write_text(json.dumps(to_payload(meta)), encoding="utf-8")
        result = DamageResult(artifacts={"damage_vector": damage, "tile_index": tiles, "metadata": metadata},
            model_name="test-model", model_version="1", meta=meta)
        result_path = self.root / "damage_result.json"
        result_path.write_text(json.dumps(to_payload(result)), encoding="utf-8")
        report = check_damage_geography(result, source, tiles, "EPSG:32650", 1, self.root / "validation")
        self.assertEqual(report.status, mode)
        return result_path, self.root / "validation/spatial_qa.json"

    def test_pass_report_and_empty_suspects_load(self):
        result_path, qa_path = self.prepare()
        view = load_spatial_qa_view(qa_path, allowed_root=self.root)
        self.assertIsNone(view.suspect_layer)
        self.assertTrue(view.samples_path.is_file())
        result = load_damage_result(result_path, allowed_root=self.root, spatial_qa_path=qa_path)
        self.assertFalse(result.synthetic)
        self.assertFalse(result.review_only)
        self.assertEqual(result.spatial_qa["metrics"]["damage_count"], 1)

    def test_warning_requires_opt_in_and_suspects_reproject(self):
        result_path, qa_path = self.prepare("warning")
        with self.assertRaisesRegex(VisualizationInputError, "须为 pass"):
            load_damage_result(result_path, allowed_root=self.root, spatial_qa_path=qa_path)
        result = load_damage_result(result_path, allowed_root=self.root, spatial_qa_path=qa_path,
                                   allow_warning_review=True)
        self.assertTrue(result.review_only)
        view = load_spatial_qa_view(qa_path, allowed_root=self.root)
        self.assertEqual(view.features[0]["properties"]["code"], "tile_edge_review")
        lon, lat = view.features[0]["geometry"]["coordinates"][0][0]
        self.assertTrue(110 < lon < 120 and -1 < lat < 1)
        markup = render_map([view.suspect_layer], [view.suspect_layer.id],
                           vector_features={view.suspect_layer.id: view.features})
        self.assertIn("tile_edge_review", markup)

    def test_fail_still_exposes_review_evidence_but_never_loads_damage(self):
        result_path, qa_path = self.prepare("fail")
        view = load_spatial_qa_view(qa_path, allowed_root=self.root)
        self.assertEqual(view.report["status"], "fail")
        self.assertTrue(view.features)
        with self.assertRaises(VisualizationInputError):
            load_damage_result(result_path, allowed_root=self.root, spatial_qa_path=qa_path,
                               allow_warning_review=True)

    def test_bad_artifact_path_is_rejected(self):
        _, qa_path = self.prepare()
        data = json.loads(qa_path.read_text())
        data["artifacts"]["suspect_samples"] = "../../../outside.csv"
        qa_path.write_text(json.dumps(data))
        with self.assertRaises(VisualizationInputError):
            load_spatial_qa_view(qa_path, allowed_root=self.root)

    def test_empty_result_remains_warning_and_zero_buildings(self):
        result_path, qa_path = self.prepare()
        frame = gpd.read_file(self.root / "damage.gpkg").iloc[:0]
        frame.to_file(self.root / "damage.gpkg", driver="GPKG")
        result = from_payload(DamageResult, json.loads(result_path.read_text()))
        report = check_damage_geography(result, self.root / "buildings.gpkg", self.root / "tiles.gpkg",
                                       "EPSG:32650", 1, qa_path.parent)
        self.assertEqual(report.status, "warning")
        view = load_damage_result(result_path, allowed_root=self.root, spatial_qa_path=qa_path,
                                  allow_warning_review=True)
        self.assertFalse(view.features)
        self.assertTrue(view.review_only)
        self.assertTrue(any("空结果" in warning for warning in view.warnings))

    def test_warning_with_failed_check_cannot_bypass_gate(self):
        result_path, qa_path = self.prepare("fail")
        data = json.loads(qa_path.read_text())
        data["status"] = "warning"
        qa_path.write_text(json.dumps(data))
        with self.assertRaisesRegex(VisualizationInputError, "失败检查"):
            load_damage_result(result_path, allowed_root=self.root, spatial_qa_path=qa_path,
                               allow_warning_review=True)

    def test_warning_review_page_uses_real_r2_output(self):
        from streamlit.testing.v1 import AppTest
        result_path, qa_path = self.prepare("warning")
        app = AppTest.from_file(str(ROOT / "app/main.py")).run(timeout=30)
        app.radio[0].set_value("阶段二 · 建筑灾损").run(timeout=30)
        app.radio[1].set_value("本地推理结果").run(timeout=30)
        app.text_input[0].set_value(str(result_path))
        app.text_input[1].set_value(str(qa_path))
        app.run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(any("R2 空间质检：warning" in item.value for item in app.warning))
        self.assertTrue(any("须为 pass" in item.value for item in app.error))
        self.assertEqual(len(app.get("iframe")), 1)  # suspect evidence only
        app.checkbox[0].check().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertTrue(any("人工复核模式" in item.value for item in app.warning))
        self.assertEqual(len(app.get("iframe")), 2)
        self.assertEqual({item.label: item.value for item in app.metric}, {"建筑总数": "1", "当前显示": "1"})
