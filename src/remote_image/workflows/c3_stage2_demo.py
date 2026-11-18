"""Explicit synthetic C1 -> R2 -> C3 smoke run; never loads a trained model."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from remote_image.core.contracts import DamageRequest, DamageResult, InferenceOptions, RasterAsset, ResultMeta, StudyArea
from remote_image.core.model_runtime import DamageRuntime
from remote_image.core.serialization import to_payload
from remote_image.modules.flood.interfaces import check_damage_geography


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@dataclass
class SyntheticDisplayAdapter:
    """Copy known synthetic predictions, not inference; owned by this demo only."""
    name: str
    version: str
    fixture: Path
    output: Path

    def predict(self, request: DamageRequest, options: InferenceOptions | None = None) -> DamageResult:
        import geopandas as gpd

        damage = json.loads((self.fixture / "damage_vector.geojson").read_text(encoding="utf-8"))
        for feature in damage["features"]:
            feature["properties"].update(event_id=request.event_id, study_area_id=request.study_area.identifier,
                                          model_name=self.name, model_version=self.version)
        damage_path = self.output / "damage_vector.gpkg"
        gpd.GeoDataFrame.from_features(damage["features"], crs="EPSG:4326").to_crs(32650).to_file(damage_path, driver="GPKG")
        tiles = json.loads((self.fixture / "tile_index.geojson").read_text(encoding="utf-8"))
        for feature in tiles["features"]:
            feature["properties"].update(event_id=request.event_id, study_area_id=request.study_area.identifier)
        tile_path = self.output / "tile_index.gpkg"
        gpd.GeoDataFrame.from_features(tiles["features"], crs="EPSG:4326").to_crs(32650).to_file(tile_path, driver="GPKG")
        meta = ResultMeta(schema_version="2.0", event_id=request.event_id,
            study_area_id=request.study_area.identifier,
            input_asset_ids=(request.post_event.asset_id,), method="building_damage", method_version=self.version,
            parameters={"fixture_only": True},
            warnings=("C1→R2→C3 合成联调：复制已知演示标签，未执行真实模型推理。",))
        metadata = self.output / "metadata.json"
        _write(metadata, to_payload(meta))
        return DamageResult(artifacts={"damage_vector": damage_path, "tile_index": tile_path, "metadata": metadata},
                            model_name=self.name, model_version=self.version, meta=meta)


def run_synthetic_handoff(project_root: Path, options: InferenceOptions | None = None) -> Path:
    """Return damage_result.json after C1 validation and actual R2 spatial QA."""
    import geopandas as gpd

    root = project_root.resolve()
    fixture = root / "tests/fixtures/stage2_synthetic"
    output = root / "outputs/c3_stage2_synthetic" / uuid4().hex
    output.mkdir(parents=True)
    manifest_path = fixture / "model_manifest.json"
    runtime = DamageRuntime(project_root=root)
    runtime.register_model_loader("fixture_damage_model", "2.0.0",
        lambda manifest, device: SyntheticDisplayAdapter(manifest.model_name, manifest.model_version, fixture, output))
    adapter = runtime.load_model(manifest_path, "cpu")
    runtime.register_model(adapter.name, adapter.version, adapter)
    request = DamageRequest(event_id="demo-flood-2023", study_area=StudyArea("demo-area",
        "POLYGON ((115.99 39.89,116.05 39.89,116.05 39.945,115.99 39.945,115.99 39.89))", "EPSG:4326"),
        post_event=RasterAsset(asset_id="demo-optical-post", path=fixture / "optical_post.tif",
            acquired_at=None, source="synthetic", source_type="satellite", bands=("R", "G", "B"),
            coordinate_reference_system="EPSG:4326", pixel_size_m=0.5),
        model_name=adapter.name, model_version=adapter.version)
    result = runtime.run_damage(request, options)
    # Persist the returned C1 parameters, not the pre-validation adapter metadata.
    _write(result.artifacts["metadata"], to_payload(result.meta))
    _write(output / "damage_result.json", to_payload(result))
    buildings = output / "synthetic_buildings.gpkg"
    gpd.read_file(result.artifacts["damage_vector"])[["building_id", "geometry"]].to_file(buildings, driver="GPKG")
    check_damage_geography(result, buildings, result.artifacts["tile_index"], "EPSG:32650", 1.0, output)
    _write(output / "run_summary.json", {"fixture_only": True, "event_id": result.meta.event_id,
        "model_name": result.model_name, "model_version": result.model_version,
        "inference_options": result.meta.parameters["inference_options"],
        "limitations": ["已知合成标签，未执行真实模型推理", "建筑底图由合成预测复制，不能验证独立定位精度"]})
    return output / "damage_result.json"
