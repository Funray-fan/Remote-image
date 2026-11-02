from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

try:
    import geopandas as gpd
    from shapely.geometry import LineString, Polygon
except ImportError:  # pragma: no cover - GIS extra is optional for the base install
    gpd = None

from remote_image.core.contracts import ContextSources, NetworkSpec, SourceRecord, StudyArea
from remote_image.modules.decision.interfaces import (
    prepare_context_layers,
    validate_context_layers,
    validate_network,
)


@unittest.skipIf(gpd is None, "需要项目的 GIS 可选依赖")
class Stage1R3Tests(unittest.TestCase):
    def setUp(self) -> None:
        # Windows 沙箱中的系统 TEMP 可能只读；测试产物固定放在仓库可写目录。
        repository_root = Path(__file__).resolve().parents[3]
        self.temp = tempfile.TemporaryDirectory(prefix="r3-stage1-", dir=repository_root)
        self.root = Path(self.temp.name)
        self.area_path = self.root / "study_area.geojson"
        self.buildings_path = self.root / "buildings.geojson"
        self.roads_path = self.root / "roads.geojson"
        gpd.GeoDataFrame(
            {"study_area_id": ["area-1"]},
            geometry=[Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])],
            crs="EPSG:3857",
        ).to_file(self.area_path, driver="GeoJSON")
        gpd.GeoDataFrame(
            {"building_id": ["b-1", "b-2"]},
            geometry=[
                Polygon([(10, 10), (20, 10), (20, 20), (10, 20)]),
                Polygon([(70, 70), (80, 70), (80, 80), (70, 80)]),
            ],
            crs="EPSG:3857",
        ).to_file(self.buildings_path, driver="GeoJSON")
        gpd.GeoDataFrame(
            {
                "edge_id": ["e-1", "e-2"],
                "oneway": ["no", "yes"],
                "speed_kmh": [30, 40],
            },
            geometry=[LineString([(0, 50), (50, 50)]), LineString([(50, 50), (100, 50)])],
            crs="EPSG:3857",
        ).to_file(self.roads_path, driver="GeoJSON")
        self.area = StudyArea("area-1", str(self.area_path), "EPSG:3857")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _sources(self) -> ContextSources:
        observed = datetime(2026, 10, 1, tzinfo=timezone.utc)
        return ContextSources(
            event_id="synthetic-stage1",
            layers={
                "buildings": SourceRecord(self.buildings_path, "synthetic buildings", observed, "CC0-1.0", "building_id"),
                "roads": SourceRecord(self.roads_path, "synthetic roads", observed, "ODbL-1.0", "edge_id"),
            },
        )

    def _network_spec(self) -> NetworkSpec:
        return NetworkSpec(
            crs="EPSG:3857",
            edge_id_field="edge_id",
            direction_field="oneway",
            speed_field="speed_kmh",
            snap_tolerance_m=0.01,
            default_speed_kmh=20,
            one_way_values=("yes",),
            blocked_field=None,
        )

    def test_prepare_context_layers_writes_standard_outputs_and_provenance(self) -> None:
        output_dir = self.root / "context"
        result = prepare_context_layers(self.area, self._sources(), "EPSG:3857", output_dir)
        self.assertEqual(set(result.layers), {"buildings", "roads"})
        self.assertTrue((output_dir / "buildings.gpkg").is_file())
        self.assertTrue((output_dir / "roads.gpkg").is_file())
        self.assertTrue((output_dir / "context_sources.json").is_file())
        self.assertTrue((output_dir / "context_layers.json").is_file())

        report = validate_context_layers(result, self.area)
        self.assertEqual(report.status, "warning")
        self.assertTrue(any(item.name == "population_layer" and item.status == "warning" for item in report.checks))
        self.assertFalse(any(item.status == "fail" for item in report.checks))

    def test_validate_network_accepts_connected_unique_edges(self) -> None:
        report = validate_network(self.roads_path, self._network_spec())
        self.assertEqual(report.status, "pass")
        self.assertEqual(report.metrics["component_count"], 1)
        self.assertEqual(report.metrics["edge_count"], 2)
        self.assertEqual(report.metrics["duplicate_edge_id_count"], 0)

    def test_validate_network_rejects_duplicate_edge_ids(self) -> None:
        duplicate_path = self.root / "duplicate_roads.geojson"
        frame = gpd.read_file(self.roads_path)
        frame["edge_id"] = ["same", "same"]
        frame.to_file(duplicate_path, driver="GeoJSON")
        report = validate_network(duplicate_path, self._network_spec())
        self.assertEqual(report.status, "fail")
        self.assertGreater(report.metrics["duplicate_edge_id_count"], 0)


if __name__ == "__main__":
    unittest.main()
