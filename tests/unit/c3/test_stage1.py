import importlib.util
import importlib.util
import unittest
from pathlib import Path

from remote_image.modules.visualization.stage1 import (
    VisualizationInputError,
    feature_ids,
    load_layers,
    load_summary,
    query_feature,
    render_map,
    render_summary,
)


FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "stage1_synthetic"
MANIFEST = FIXTURE / "layer_manifest.json"


class Stage1VisualizationTests(unittest.TestCase):
    def test_loads_manifest_layers_in_display_order(self):
        layers = load_layers(MANIFEST)
        self.assertEqual(
            [layer.id for layer in layers],
            ["pre-event", "post-event", "flood-mask", "flood-polygons", "buildings", "roads"],
        )
        self.assertTrue(all(layer.path.is_file() for layer in layers))

    def test_renders_offline_svg_with_clickable_features(self):
        markup = render_map(load_layers(MANIFEST), ["flood-polygons"])
        self.assertIn("<svg", markup)
        self.assertIn('data-feature-id="flood-001"', markup)
        self.assertIn("点击地图要素查看属性", markup)
        self.assertNotIn("https://", markup)

    def test_renders_georeferenced_raster_fixture(self):
        if importlib.util.find_spec("rasterio") is None:
            self.skipTest("rasterio is optional; install the project's [gis] extra")
        markup = render_map(load_layers(MANIFEST), ["flood-mask"])
        self.assertIn("data:image/png;base64,", markup)

    def test_query_feature_and_ids(self):
        path = FIXTURE / "flood_polygons.geojson"
        self.assertEqual(feature_ids(path), ["flood-001"])
        feature = query_feature(path, "flood-001")
        self.assertEqual(feature["properties"]["area_m2"], 120000)
        self.assertIsNone(query_feature(path, "missing"))

    def test_summary_is_passed_through_without_recalculation(self):
        summary = render_summary(load_summary(FIXTURE / "summary.json"))
        self.assertEqual(summary["event_id"], "demo-flood-2023")
        self.assertEqual(summary["statistics"]["affected_buildings"], 18)
        self.assertEqual(summary["metadata"]["method_version"], "synthetic-baseline-0.1")

    def test_missing_manifest_is_rejected(self):
        with self.assertRaises(VisualizationInputError):
            load_layers(FIXTURE / "missing_manifest.json")

    def test_missing_artifact_is_rejected(self):
        with self.assertRaisesRegex(VisualizationInputError, "图层文件不存在"):
            load_layers(FIXTURE / "invalid_missing_artifact_manifest.json")

    def test_projected_vector_is_rejected_instead_of_misplaced(self):
        layers = load_layers(FIXTURE / "invalid_projected_manifest.json")
        with self.assertRaisesRegex(VisualizationInputError, "EPSG:4326"):
            render_map(layers)

    def test_duplicate_layer_ids_are_rejected(self):
        with self.assertRaisesRegex(VisualizationInputError, "图层 id 重复"):
            load_layers(FIXTURE / "invalid_duplicate_manifest.json")

    @unittest.skipUnless(importlib.util.find_spec("streamlit"), "install .[ui] to test the Streamlit page")
    def test_streamlit_page_smoke(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(Path(__file__).resolve().parents[3] / "app" / "main.py"))
        app.session_state["case"] = "合成功能样例"
        app.run(timeout=30)
        self.assertFalse(app.exception)
        self.assertIn("洪水范围", [item.label for item in app.checkbox])
        self.assertIn("受影响建筑数", [item.label for item in app.metric])
        self.assertEqual(len(app.warning), 1)

    @unittest.skipUnless(importlib.util.find_spec("streamlit"), "requires UI dependencies")
    def test_cleared_case_selector_shows_prompt(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(Path(__file__).resolve().parents[3] / "app" / "main.py"))
        app.session_state['case'] = '合成功能样例'
        app.run(timeout=30)
        app.session_state['case'] = None
        app.run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(any('请选择一个案例' in item.value for item in app.info))


if __name__ == "__main__":
    unittest.main()
