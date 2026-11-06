"""转面与投影面积的合成样例，不代表洪水识别精度。"""
from pathlib import Path
import tempfile
import unittest

import geopandas as gpd
import numpy as np
import pyogrio
import rasterio
from rasterio.transform import from_origin

from remote_image.core.contracts import FloodContext
from remote_image.modules.flood.qa import R2Error
from remote_image.modules.flood.vectorization import (
    export_geojson, polygonize_mask, verify_vector_mask,
)


class R2VectorizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r2-vectorization-")
        self.root = Path(self.temp.name)
        self.ctx = FloodContext("fixture_event", "fixture_area", "sar_post_threshold",
                                "test-1", {"run_id": "fixture_run"}, "EPSG:32650")

    def tearDown(self):
        self.temp.cleanup()

    def write_mask(self, values, name="mask.tif", crs="EPSG:32650"):
        values = np.asarray(values, dtype=np.uint8)
        path = self.root / name
        with rasterio.open(path, "w", driver="GTiff", height=values.shape[0],
                           width=values.shape[1], count=1, dtype="uint8", crs=crs,
                           transform=from_origin(500000, 4400000, 10, 10), nodata=255) as ds:
            ds.write(values, 1)
        return path

    def test_hole_unknown_and_projected_area(self):
        values = np.ones((5, 5), np.uint8)
        values[1:4, 1:4] = 0
        values[2, 2] = 255
        mask = self.write_mask(values)
        output = polygonize_mask(mask, self.ctx, self.root / "flood.gpkg")
        frame = gpd.read_file(output, layer="flood_polygons")
        self.assertEqual(frame.crs.to_epsg(), 32650)
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["pixel_count"], 16)
        self.assertAlmostEqual(frame.iloc[0]["area_m2"], 1600)
        self.assertEqual(frame.iloc[0]["event_id"], "fixture_event")
        self.assertEqual(frame.iloc[0]["run_id"], "fixture_run")
        self.assertEqual(len(frame.geometry.iloc[0].geoms[0].interiors), 1)
        report = verify_vector_mask(mask, output)
        self.assertEqual(report["mismatch_pixels"], 0)
        self.assertAlmostEqual(report["area_difference_m2"], 0)

    def test_diagonal_pixels_are_separate_four_neighbour_features(self):
        mask = self.write_mask([[1, 0], [0, 1]])
        output = polygonize_mask(mask, self.ctx, self.root / "diagonal.gpkg")
        frame = gpd.read_file(output, layer="flood_polygons")
        self.assertEqual(len(frame), 2)
        self.assertEqual(frame["pixel_count"].tolist(), [1, 1])
        self.assertEqual(frame["candidate_id"].nunique(), 2)
        self.assertTrue(frame.is_valid.all())

    def test_empty_gpkg_has_legal_layer_and_exports_empty_geojson(self):
        mask = self.write_mask([[0, 255], [0, 0]])
        output = polygonize_mask(mask, self.ctx, self.root / "empty.gpkg")
        info = pyogrio.read_info(output, layer="flood_polygons")
        self.assertEqual(info["features"], 0)
        self.assertIn("area_m2", info["fields"])
        self.assertEqual(verify_vector_mask(mask, output)["candidate_pixels"], 0)
        geographic = export_geojson(output, self.root / "empty.geojson")
        self.assertTrue(gpd.read_file(geographic).empty)
        # 空 GeoJSON 不保存字段 schema，但依然应为合法空 FeatureCollection。
        self.assertTrue(geographic.is_file())
        self.assertEqual(verify_vector_mask(mask, geographic)["candidate_pixels"], 0)
        direct = polygonize_mask(mask, self.ctx, self.root / "empty-direct.geojson")
        self.assertEqual(verify_vector_mask(mask, direct)["mismatch_pixels"], 0)

    def test_geojson_roundtrip_preserves_area_properties_and_pixels(self):
        mask = self.write_mask([[1, 1, 0], [1, 255, 0], [0, 0, 1]])
        analysis = polygonize_mask(mask, self.ctx, self.root / "analysis.gpkg")
        geographic = export_geojson(analysis, self.root / "display.geojson")
        frame = gpd.read_file(geographic)
        self.assertEqual(frame.crs.to_epsg(), 4326)
        self.assertAlmostEqual(frame["area_m2"].sum(), 400)
        self.assertEqual(verify_vector_mask(mask, geographic)["mismatch_pixels"], 0)
        direct = polygonize_mask(mask, self.ctx, self.root / "direct.geojson")
        self.assertEqual(verify_vector_mask(mask, direct)["mismatch_pixels"], 0)

    def test_displaced_and_corrupt_area_vectors_are_detected(self):
        mask = self.write_mask([[1, 0, 0], [0, 0, 0]])
        analysis = polygonize_mask(mask, self.ctx, self.root / "correct.gpkg")
        frame = gpd.read_file(analysis, layer="flood_polygons")
        frame.geometry = frame.geometry.translate(xoff=10)
        shifted = self.root / "shifted.gpkg"
        frame.to_file(shifted, layer="flood_polygons", driver="GPKG", engine="pyogrio")
        with self.assertRaises(R2Error) as raised:
            verify_vector_mask(mask, shifted)
        self.assertEqual(raised.exception.code, "ARTIFACT_MISMATCH")
        frame = gpd.read_file(analysis, layer="flood_polygons")
        frame["area_m2"] = 200
        wrong_area = self.root / "wrong-area.gpkg"
        frame.to_file(wrong_area, layer="flood_polygons", driver="GPKG", engine="pyogrio")
        with self.assertRaises(R2Error):
            verify_vector_mask(mask, wrong_area)

    def test_unknown_codes_and_geographic_analysis_are_rejected(self):
        invalid = self.write_mask([[1, 2]])
        with self.assertRaises(R2Error) as raised:
            polygonize_mask(invalid, self.ctx, self.root / "invalid.gpkg")
        self.assertEqual(raised.exception.code, "INVALID_MASK")
        geographic = self.write_mask([[1]], name="geographic.tif", crs="EPSG:4326")
        with self.assertRaises(R2Error) as raised:
            polygonize_mask(geographic, self.ctx, self.root / "invalid-area.gpkg")
        self.assertEqual(raised.exception.code, "INVALID_AREA_CRS")


if __name__ == "__main__":
    unittest.main()
