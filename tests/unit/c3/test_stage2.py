import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from shutil import copytree

from remote_image.modules.visualization.stage1 import VisualizationInputError, load_manifest, render_map
from remote_image.modules.visualization.stage2 import (
    DamageMapHandle,
    damage_counts,
    load_damage_result,
    render_damage_layer,
    show_building_detail,
)


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests/fixtures/stage2_synthetic"
HAS_GIS = importlib.util.find_spec("rasterio") is not None


class Stage2VisualizationTests(unittest.TestCase):
    def test_threshold_preserves_source_and_filters_by_building_id(self):
        result = load_damage_result(FIXTURE / "damage_result.json", allowed_root=ROOT)
        handle = DamageMapHandle(result.event_id)
        layer = render_damage_layer(result.event_id, result, handle, 0.82)
        self.assertEqual(damage_counts(result.features)["major-damage"], 2)
        self.assertEqual(set(handle.buildings), {"DEMO-001", "DEMO-003", "DEMO-004"})
        self.assertEqual(show_building_detail(result.event_id, layer, "DEMO-003", handle)["confidence"], 0.82)
        self.assertIsNone(show_building_detail(result.event_id, layer, "DEMO-006", handle))
        self.assertIsNone(show_building_detail("other", layer, "DEMO-003", handle))
        self.assertEqual(result.features["DEMO-006"]["properties"]["confidence"], 0.62)
        markup = render_map(handle.layers, vector_features={layer: handle.buildings.values()})
        self.assertIn('data-feature-id="DEMO-003"', markup)
        self.assertIn('fill="#ea580c"', markup)
        self.assertNotIn('data-feature-id="DEMO-006"', markup)

    def test_cross_event_overlay_is_rejected(self):
        result = load_damage_result(FIXTURE / "damage_result.json", allowed_root=ROOT)
        with self.assertRaisesRegex(VisualizationInputError, "同一事件"):
            render_damage_layer(result.event_id, result, DamageMapHandle("different-event"))

    def test_non_fixture_requires_passed_spatial_qa(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = copytree(FIXTURE, root / "event")
            result_path = data / "damage_result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["meta"]["parameters"] = {}
            result_path.write_text(json.dumps(result), encoding="utf-8")
            (data / "metadata.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(VisualizationInputError, "spatial_qa.json"):
                load_damage_result(result_path, allowed_root=root)
            qa = data / "spatial_qa.json"
            qa.write_text('{"status":"warning"}', encoding="utf-8")
            with self.assertRaisesRegex(VisualizationInputError, "须为 pass"):
                load_damage_result(result_path, allowed_root=root)
            qa.write_text('{"status":"pass","event_id":"other"}', encoding="utf-8")
            with self.assertRaisesRegex(VisualizationInputError, "事件 ID"):
                load_damage_result(result_path, allowed_root=root)
            qa.write_text('{"status":"pass"}', encoding="utf-8")
            self.assertFalse(load_damage_result(result_path, allowed_root=root).synthetic)

    def test_masks_alone_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "damage_result.json"
            result = json.loads((FIXTURE / path.name).read_text(encoding="utf-8"))
            del result["artifacts"]["damage_vector"]
            result["artifacts"]["building_mask"] = "buildings.tif"
            path.write_text(json.dumps(result), encoding="utf-8")
            with self.assertRaisesRegex(VisualizationInputError, "逐建筑"):
                load_damage_result(path, allowed_root=root)

    def test_invalid_building_attributes_and_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = copytree(FIXTURE, root / "event")
            path = data / "damage_vector.geojson"
            original = path.read_text(encoding="utf-8")
            for field, value in (
                ("confidence", float("nan")), ("confidence", True), ("confidence", None),
                ("damage_class", "invalid"), ("event_id", "wrong-event"), ("model_version", "wrong-version"),
            ):
                with self.subTest(field=field, value=value):
                    vector = json.loads(original)
                    vector["features"][0]["properties"][field] = value
                    path.write_text(json.dumps(vector), encoding="utf-8")
                    with self.assertRaises(VisualizationInputError):
                        load_damage_result(data / "damage_result.json", allowed_root=root)
            vector = json.loads(original)
            vector["features"][1]["properties"]["building_id"] = "DEMO-001"
            path.write_text(json.dumps(vector), encoding="utf-8")
            with self.assertRaisesRegex(VisualizationInputError, "重复建筑"):
                load_damage_result(data / "damage_result.json", allowed_root=root)
            path.write_text(original, encoding="utf-8")
            result_path = data / "damage_result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["artifacts"]["damage_vector"] = "../../outside.geojson"
            result_path.write_text(json.dumps(result), encoding="utf-8")
            with self.assertRaisesRegex(VisualizationInputError, "仓库内"):
                load_damage_result(result_path, allowed_root=root)

    def test_fixture_matches_published_schemas(self):
        if importlib.util.find_spec("jsonschema") is None:
            self.skipTest("install .[dev]")
        from jsonschema import Draft202012Validator

        for artifact, schema in (
            ("damage_result.json", "damage-result.schema.json"),
            ("damage_vector.geojson", "damage-vector.schema.json"),
            ("tile_index.geojson", "tile-index.schema.json"),
        ):
            validator = Draft202012Validator(json.loads((ROOT / "schemas/v1" / schema).read_text(encoding="utf-8")))
            validator.validate(json.loads((FIXTURE / artifact).read_text(encoding="utf-8")))

    @unittest.skipUnless(HAS_GIS and importlib.util.find_spec("geopandas"), "install .[gis]")
    def test_geopackage_is_reprojected_for_display(self):
        import geopandas as gpd

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = copytree(FIXTURE, root / "event")
            path = data / "damage_result.json"
            result = json.loads(path.read_text(encoding="utf-8"))
            frame = gpd.read_file(data / "damage_vector.geojson").to_crs(3857)
            frame.to_file(data / "damage.gpkg", driver="GPKG")
            result["artifacts"]["damage_vector"] = "damage.gpkg"
            path.write_text(json.dumps(result), encoding="utf-8")
            read = load_damage_result(path, allowed_root=root)
            lon, lat = read.features["DEMO-001"]["geometry"]["coordinates"][0][0]
            self.assertAlmostEqual(lon, 116.008, places=6)
            self.assertAlmostEqual(lat, 39.922, places=6)

    @unittest.skipUnless(HAS_GIS, "install .[gis]")
    def test_optical_rgb_and_stage1_flood_render_together(self):
        result = load_damage_result(FIXTURE / "damage_result.json", allowed_root=ROOT)
        optical = load_manifest(FIXTURE / "layer_manifest.json", allowed_root=ROOT)
        flood = load_manifest(FIXTURE.parent / "stage1_synthetic/layer_manifest.json", allowed_root=ROOT)
        self.assertEqual(optical["event_id"], flood["event_id"])
        handle = DamageMapHandle(result.event_id, [*optical["layers"], *flood["layers"]])
        layer = render_damage_layer(result.event_id, result, handle)
        markup = render_map(
            handle.layers, ["demo-optical-post", "flood-polygons", layer],
            vector_features={layer: handle.buildings.values()},
        )
        self.assertIn("data:image/png;base64,", markup)
        self.assertIn('data-feature-id="flood-001"', markup)
        self.assertIn('data-feature-id="DEMO-003"', markup)

    @unittest.skipUnless(HAS_GIS and importlib.util.find_spec("streamlit"), "install .[ui,gis]")
    def test_page_loads_fixture_and_updates_display_count(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(ROOT / "app/main.py")).run(timeout=30)
        app.radio[0].set_value("阶段二 · 建筑灾损").run(timeout=30)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        frames = app.get("iframe")
        self.assertEqual(len(frames), 1)
        self.assertIn('data-feature-id="DEMO-004"', frames[0].proto.srcdoc)
        self.assertIn("function zoomMap", frames[0].proto.srcdoc)
        self.assertIn("合成演示", app.warning[0].value)
        self.assertEqual({m.label: m.value for m in app.metric}, {"建筑总数": "6", "当前显示": "6"})
        app.slider[0].set_value(0.9).run(timeout=30)
        self.assertFalse(app.error)
        self.assertEqual(app.metric[1].value, "2")
        app.selectbox[0].select("DEMO-004").run(timeout=30)
        self.assertIn("原始置信度：0.94", app.text[1].value)
