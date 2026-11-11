from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from remote_image.modules.data.r1_preprocessing import (  # noqa: E402
    AssetRecord,
    StudyArea,
    prepare_pair,
    raster_asset_from_path,
    register_asset,
    validate_raster,
)


class R1PreprocessingTests(unittest.TestCase):
    def test_register_validate_and_prepare_aligned_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transform = from_origin(500000, 4400000, 10, 10)
            rasters = []
            for name, offset in (("pre", 0), ("post", 10)):
                path = root / f"{name}.tif"
                with rasterio.open(path, "w", driver="GTiff", width=40, height=40, count=1, dtype="float32", crs="EPSG:32650", transform=transform, nodata=-9999) as ds:
                    ds.write(np.full((40, 40), offset + 1, dtype="float32"), 1)
                rasters.append(raster_asset_from_path(path, name, "fixture", ("VV",), acquired_at="2023-07-24T10:00:00Z"))

            area = StudyArea("fixture_event", {"bbox": [500050, 4399700, 500300, 4399950]}, "EPSG:32650")
            report = validate_raster(rasters[0], area, ("VV",))
            self.assertEqual(report.status, "pass")
            self.assertTrue(all(check.status == "pass" for check in report.checks))

            catalog = root / "asset_catalog.json"
            record = AssetRecord("pre", None, "2026-10-26T00:00:00Z", "fixture", None, {}, (None, None), "acquired")
            register_asset(rasters[0], record, catalog)
            stored = json.loads(catalog.read_text(encoding="utf-8"))["assets"][0]
            self.assertEqual(len(stored["sha256"]), 64)

            result = prepare_pair(rasters[0], rasters[1], area, "EPSG:32650", None, "nearest", root / "prepared")
            paths = [result.pre_event.path, result.post_event.path, result.valid_mask]
            metadata = []
            for path in paths:
                with rasterio.open(path) as ds:
                    metadata.append((ds.crs, ds.transform, ds.width, ds.height))
            self.assertEqual(metadata[0], metadata[1])
            self.assertEqual(metadata[0], metadata[2])
            self.assertTrue(result.metadata.exists())


if __name__ == "__main__":
    unittest.main()
