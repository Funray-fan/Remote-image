"""Synthetic Stage 2 adapters used only by C1 integration tests."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from remote_image.core.contracts import (
    SCHEMA_VERSION,
    DamageRequest,
    DamageResult,
    InferenceOptions,
    ModelManifest,
    ResultMeta,
    utc_now,
)
from remote_image.core.serialization import to_payload


@dataclass
class FixtureDamageModel:
    name: str
    version: str
    output_root: Path
    artifact_format: str = "geojson"
    damage_class: str = "minor-damage"
    corrupt_gpkg: bool = False
    predict_calls: int = 0

    def predict(
        self,
        request: DamageRequest,
        options: InferenceOptions | None = None,
    ) -> DamageResult:
        self.predict_calls += 1
        safe_event = re.sub(r"[^A-Za-z0-9._-]+", "_", request.event_id).strip("._")
        if not safe_event:
            raise ValueError("event_id cannot produce an output directory")
        output_dir = self.output_root / safe_event / "stage2"
        output_dir.mkdir(parents=True, exist_ok=True)

        suffix = ".gpkg" if self.artifact_format == "gpkg" else ".geojson"
        damage_path = output_dir / f"damage_vector{suffix}"
        tile_path = output_dir / f"tile_index{suffix}"
        metadata_path = output_dir / "metadata.json"

        damage_properties = {
            "event_id": request.event_id,
            "study_area_id": request.study_area.identifier,
            "building_id": "building-1",
            "damage_class": self.damage_class,
            "confidence": 0.75,
            "reason": None,
            "model_name": self.name,
            "model_version": self.version,
        }
        tile_properties = {
            "event_id": request.event_id,
            "study_area_id": request.study_area.identifier,
            "tile_id": "tile-0-0",
            "row": 0,
            "column": 0,
        }
        if self.artifact_format == "gpkg":
            _write_gpkg(damage_path, "damage_vector", damage_properties)
            _write_gpkg(tile_path, "tile_index", tile_properties)
            if self.corrupt_gpkg:
                damage_path.write_bytes(b"not a sqlite database")
        else:
            _write_geojson(damage_path, damage_properties)
            _write_geojson(tile_path, tile_properties)

        input_ids = tuple(
            asset.asset_id
            for asset in (request.pre_event, request.post_event)
            if asset is not None
        )
        meta = ResultMeta(
            schema_version=SCHEMA_VERSION,
            event_id=request.event_id,
            study_area_id=request.study_area.identifier,
            input_asset_ids=input_ids,
            method=request.task,
            method_version=self.version,
            parameters={
                "fixture_only": True,
                "inference_options": asdict(options) if options is not None else {},
            },
            created_at=utc_now(),
            warnings=("synthetic interface fixture; not a real damage assessment",),
        )
        metadata_path.write_text(
            json.dumps(to_payload(meta), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return DamageResult(
            artifacts={
                "damage_vector": damage_path,
                "tile_index": tile_path,
                "metadata": metadata_path,
            },
            model_name=self.name,
            model_version=self.version,
            meta=meta,
        )


class FixtureModelLoader:
    """Callable loader with the same boundary C2 will implement."""

    def __init__(self, output_root: Path, **adapter_options: object) -> None:
        self.output_root = output_root
        self.adapter_options = adapter_options
        self.calls = 0
        self.adapter: FixtureDamageModel | None = None

    def __call__(self, manifest: ModelManifest, device: str) -> FixtureDamageModel:
        self.calls += 1
        if device not in manifest.inference_limits.allowed_devices:
            raise ValueError("fixture loader received an unsupported device")
        self.adapter = FixtureDamageModel(
            name=manifest.model_name,
            version=manifest.model_version,
            output_root=self.output_root,
            **self.adapter_options,
        )
        return self.adapter


def _write_geojson(path: Path, properties: dict[str, object]) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                },
                "properties": properties,
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_gpkg(path: Path, layer: str, properties: dict[str, object]) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT)")
        connection.execute(
            "CREATE TABLE gpkg_geometry_columns "
            "(table_name TEXT, column_name TEXT, geometry_type_name TEXT)"
        )
        columns = ", ".join(
            f'"{name}" {_sqlite_type(value)}' for name, value in properties.items()
        )
        connection.execute(
            f'CREATE TABLE "{layer}" (fid INTEGER PRIMARY KEY, geom BLOB NOT NULL, {columns})'
        )
        connection.execute(
            "INSERT INTO gpkg_contents (table_name, data_type) VALUES (?, 'features')",
            (layer,),
        )
        connection.execute(
            "INSERT INTO gpkg_geometry_columns "
            "(table_name, column_name, geometry_type_name) VALUES (?, 'geom', 'POLYGON')",
            (layer,),
        )
        names = ", ".join(f'"{name}"' for name in properties)
        placeholders = ", ".join("?" for _ in properties)
        connection.execute(
            f'INSERT INTO "{layer}" (geom, {names}) VALUES (?, {placeholders})',
            (b"GP", *properties.values()),
        )
        connection.commit()
    finally:
        connection.close()


def _sqlite_type(value: object) -> str:
    if isinstance(value, bool):
        return "INTEGER"
    if isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "REAL"
    return "TEXT"
