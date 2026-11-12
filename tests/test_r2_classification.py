"""分类与连通域的合成样例，只验证程序逻辑。"""
from pathlib import Path
import tempfile
import unittest

import numpy as np
import rasterio
from rasterio.transform import from_origin

from remote_image.modules.flood.classification import (
    classify_arrays, classify_rasters, clean_components,
)
from remote_image.modules.flood.qa import R2Error


def write_raster(path, values, *, transform=None, nodata=None):
    values = np.asarray(values)
    with rasterio.open(path, "w", driver="GTiff", height=values.shape[0],
                       width=values.shape[1], count=1, dtype=values.dtype,
                       crs="EPSG:32650", transform=transform or from_origin(500000, 4400000, 10, 10),
                       nodata=nodata) as ds:
        ds.write(values, 1)
    return path


class R2ClassificationArrayTests(unittest.TestCase):
    def test_common_threshold_boundary_nodata_and_nonfinite(self):
        pre = np.array([[-10, -20, -15, -14, np.nan]], dtype=np.float32)
        post = np.array([[-20, -20, -16, -15, -20]], dtype=np.float32)
        valid = np.ones(pre.shape, dtype=bool)
        result = classify_arrays(pre, post, valid, -15)
        np.testing.assert_array_equal(result, [[1, 0, 1, 0, 255]])
        valid[0, 0] = False
        self.assertEqual(classify_arrays(pre, post, valid, -15)[0, 0], 255)
        self.assertEqual(result.dtype, np.uint8)

    def test_identical_inputs_do_not_create_change(self):
        values = np.array([[-25, -15, -10], [-4, 0, 2]], dtype=np.float32)
        result = classify_arrays(values, values, np.ones(values.shape, bool), -15)
        self.assertFalse(np.any(result == 1))

    def test_invalid_threshold_and_non_boolean_mask_are_rejected(self):
        values = np.zeros((2, 2), np.float32)
        for threshold in (np.nan, np.inf, None, True):
            with self.subTest(threshold=threshold), self.assertRaises(R2Error):
                classify_arrays(values, values, np.ones((2, 2), bool), threshold)
        with self.assertRaises(R2Error):
            classify_arrays(values, values, np.full((2, 2), 255, np.uint8), -15)

    def test_four_neighbours_and_exact_area_limit(self):
        values = np.array([[1, 0, 0, 0], [0, 1, 255, 0], [0, 0, 1, 1]], np.uint8)
        cleaned, stats = clean_components(values, 200, 100)
        np.testing.assert_array_equal(cleaned, [[0, 0, 0, 0], [0, 0, 255, 0], [0, 0, 1, 1]])
        self.assertEqual(stats["components_before"], 3)
        self.assertEqual(stats["components_after"], 1)
        self.assertEqual(stats["candidate_area_m2"], 200)
        removed, _ = clean_components(values, 201, 100)
        self.assertFalse(np.any(removed == 1))
        unchanged, _ = clean_components(values, 0, 100)
        np.testing.assert_array_equal(unchanged, values)

    def test_holes_and_unknown_are_preserved(self):
        values = np.ones((5, 5), np.uint8)
        values[2, 2] = 0
        values[1, 1] = 255
        cleaned, stats = clean_components(values, 200, 100)
        np.testing.assert_array_equal(cleaned, values)
        self.assertEqual(stats["unknown_pixels"], 1)
        self.assertEqual(stats["observed_area_m2"], 2400)
        for invalid in (-1, np.inf):
            with self.assertRaises(R2Error):
                clean_components(values, invalid, 100)


class R2ClassificationRasterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r2-classification-")
        self.root = Path(self.temp.name)
        self.pre = write_raster(self.root / "pre.tif", np.full((6, 8), -10, np.float32), nodata=-9999)
        self.valid = write_raster(self.root / "valid.tif", np.ones((6, 8), np.uint8), nodata=0)

    def tearDown(self):
        self.temp.cleanup()

    def test_global_components_cross_window_boundaries(self):
        values = np.full((6, 8), -10, np.float32)
        values[3, 1:7] = -20
        values[0, 0] = -20
        post = write_raster(self.root / "post.tif", values, nodata=-9999)
        results = []
        for size in (2, 5, 1024):
            output = self.root / f"result-{size}.tif"
            report = classify_rasters(self.pre, post, self.valid, -15, 600, output, window_size=size)
            self.assertEqual(report["candidate_pixels"], 6)
            self.assertEqual(report["components_after"], 1)
            with rasterio.open(output) as ds:
                self.assertEqual(ds.nodata, 255)
                self.assertEqual(ds.crs.to_epsg(), 32650)
                self.assertEqual(ds.transform, from_origin(500000, 4400000, 10, 10))
                results.append(ds.read(1))
        np.testing.assert_array_equal(results[0], results[1])
        np.testing.assert_array_equal(results[1], results[2])
        self.assertEqual(results[0][0, 0], 0)

    def test_auxiliary_unknown_wins_over_permanent_water(self):
        post = write_raster(self.root / "post.tif", np.full((6, 8), -20, np.float32))
        permanent = np.zeros((6, 8), np.uint8)
        permanent[0, 0] = 1
        permanent[0, 1] = 255
        permanent[0, 2] = 1
        exclusion = np.zeros((6, 8), np.uint8)
        exclusion[0, 2] = 255
        exclusion[0, 3] = 1
        permanent_path = write_raster(self.root / "permanent.tif", permanent, nodata=255)
        exclusion_path = write_raster(self.root / "exclusion.tif", exclusion, nodata=255)
        output = self.root / "auxiliary.tif"
        report = classify_rasters(self.pre, post, self.valid, -15, 0, output,
                                  permanent_path, exclusion_path, window_size=3)
        with rasterio.open(output) as ds:
            np.testing.assert_array_equal(ds.read(1)[0, :5], [0, 255, 255, 255, 1])
        self.assertEqual(report["auxiliary_unknown_pixels"], 2)
        self.assertEqual(report["excluded_pixels"], 1)
        self.assertEqual(report["permanent_water_pixels"], 1)

    def test_mask_conflicts_and_empty_observations_fail(self):
        values = np.full((6, 8), -20, np.float32)
        values[0, 0] = -9999
        post = write_raster(self.root / "post.tif", values, nodata=-9999)
        with self.assertRaises(R2Error) as raised:
            classify_rasters(self.pre, post, self.valid, -15, 0, self.root / "conflict.tif")
        self.assertEqual(raised.exception.code, "MASK_SOURCE_CONFLICT")
        no_valid = write_raster(self.root / "none.tif", np.zeros((6, 8), np.uint8), nodata=0)
        with self.assertRaises(R2Error) as raised:
            classify_rasters(self.pre, post, no_valid, -15, 0, self.root / "empty.tif")
        self.assertEqual(raised.exception.code, "NO_VALID_DATA")

    def test_bad_auxiliary_grid_and_codes_are_rejected(self):
        post = write_raster(self.root / "post.tif", np.full((6, 8), -20, np.float32))
        bad_grid = write_raster(self.root / "bad-grid.tif", np.zeros((6, 8), np.uint8),
                                transform=from_origin(500010, 4400000, 10, 10))
        with self.assertRaises(R2Error) as raised:
            classify_rasters(self.pre, post, self.valid, -15, 0, self.root / "grid.tif", bad_grid)
        self.assertEqual(raised.exception.code, "AUXILIARY_MASK_MISMATCH")
        bad_codes = write_raster(self.root / "bad-codes.tif", np.full((6, 8), 2, np.uint8))
        with self.assertRaises(R2Error) as raised:
            classify_rasters(self.pre, post, self.valid, -15, 0, self.root / "codes.tif", bad_codes)
        self.assertEqual(raised.exception.code, "INVALID_MASK")

    def test_input_cannot_be_overwritten(self):
        with self.assertRaises(R2Error) as raised:
            classify_rasters(self.pre, self.pre, self.valid, -15, 0, self.pre)
        self.assertEqual(raised.exception.code, "OUTPUT_CONFLICT")


if __name__ == "__main__":
    unittest.main()
