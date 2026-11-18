"""C1 validation at the v2 damage-model handoff boundary."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from remote_image.core.contracts import (
    DamageRequest,
    DamageResult,
    ModelManifest,
    RasterAsset,
)
from remote_image.core.errors import ErrorCode, PipelineError
from remote_image.core.serialization import to_payload
from remote_image.core.validation import ContractValidationError, validate_contract, validate_payload
from remote_image.modules.damage.contract_check import validate_damage_response


MODULE = "core.damage_validation"
_ALLOWED_ARTIFACTS = {
    "damage_vector",
    "damage_mask",
    "building_mask",
    "tile_index",
    "metadata",
}
_DAMAGE_PROPERTIES = (
    "event_id",
    "study_area_id",
    "building_id",
    "damage_class",
    "confidence",
    "reason",
    "model_name",
    "model_version",
)
_TILE_PROPERTIES = (
    "event_id",
    "study_area_id",
    "tile_id",
    "row",
    "column",
)


@dataclass(frozen=True)
class DamageValidationReport:
    errors: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors


def validate_request_for_manifest(request: DamageRequest, manifest: ModelManifest) -> None:
    """Reject requests before a model receives incompatible inputs."""

    try:
        validate_contract(request)
    except ContractValidationError as exc:
        raise _input_error("DamageRequest does not satisfy the v2 contract.", cause=str(exc)) from exc

    if (request.model_name, request.model_version) != (
        manifest.model_name,
        manifest.model_version,
    ):
        raise _input_error(
            "Request model identity does not match the loaded manifest.",
            model_name=request.model_name,
            model_version=request.model_version,
        )
    if request.task != manifest.task:
        raise _input_error(
            "Request task does not match the model task.",
            request_task=request.task,
            model_task=manifest.task,
        )
    spec = manifest.input_spec
    if spec.requires_pre_event and request.pre_event is None:
        raise PipelineError(
            ErrorCode.INPUT_MISSING,
            "The model requires a pre-event raster.",
            module=MODULE,
            details={"model_name": manifest.model_name, "model_version": manifest.model_version},
        )
    if (
        manifest.object_aggregation.geometry_source == "request_footprints"
        and request.building_footprints is None
    ):
        raise PipelineError(
            ErrorCode.INPUT_MISSING,
            "The model aggregates against request building footprints.",
            module=MODULE,
            details={"model_name": manifest.model_name},
        )
    if request.building_footprints is not None and not request.building_footprints.is_file():
        raise PipelineError(
            ErrorCode.INPUT_MISSING,
            "building_footprints does not reference an existing file.",
            module=MODULE,
            details={"building_footprints": str(request.building_footprints)},
        )

    assets = tuple(
        (label, asset)
        for label, asset in (
            ("pre_event", request.pre_event),
            ("post_event", request.post_event),
        )
        if asset is not None
    )
    for label, asset in assets:
        _validate_asset(label, asset, manifest)
    if request.pre_event is not None:
        if _normalized_crs(request.pre_event.coordinate_reference_system) != _normalized_crs(
            request.post_event.coordinate_reference_system
        ):
            raise _input_error(
                "Pre-event and post-event rasters must use the same CRS.",
                pre_event_crs=request.pre_event.coordinate_reference_system,
                post_event_crs=request.post_event.coordinate_reference_system,
            )


def validate_damage_output(
    request: DamageRequest,
    manifest: ModelManifest,
    result: DamageResult,
) -> DamageValidationReport:
    """Validate result identity, feature properties, and artifact files."""

    errors: list[str] = []
    try:
        validate_damage_response(request, result, validate_artifacts=False)
    except (ContractValidationError, ValueError, TypeError) as exc:
        return DamageValidationReport((f"result contract mismatch: {exc}",))

    artifact_keys = set(result.artifacts)
    unknown = artifact_keys - _ALLOWED_ARTIFACTS
    if unknown:
        errors.append(f"unknown artifact keys: {sorted(unknown)}")
    required = {"tile_index", "metadata"}
    if manifest.task == "building_damage":
        required.add("damage_vector")
    missing = required - artifact_keys
    if missing:
        errors.append(f"missing required artifacts: {sorted(missing)}")

    for name, path in result.artifacts.items():
        if not path.is_file():
            errors.append(f"artifact {name} does not exist: {path}")

    damage_vector = result.artifacts.get("damage_vector")
    if damage_vector is not None and damage_vector.is_file():
        collection_errors, collection = _load_collection(
            damage_vector, "damage-vector", _DAMAGE_PROPERTIES
        )
        errors.extend(collection_errors)
        if collection is not None:
            errors.extend(_validate_damage_features(collection, request, manifest, result))

    tile_index = result.artifacts.get("tile_index")
    if tile_index is not None and tile_index.is_file():
        collection_errors, collection = _load_collection(
            tile_index, "tile-index", _TILE_PROPERTIES
        )
        errors.extend(collection_errors)
        if collection is not None:
            errors.extend(_validate_tile_features(collection, request))

    metadata = result.artifacts.get("metadata")
    if metadata is not None and metadata.is_file():
        errors.extend(_validate_metadata(metadata, result))
    return DamageValidationReport(tuple(errors))


def _validate_asset(label: str, asset: RasterAsset, manifest: ModelManifest) -> None:
    if not asset.path.is_file():
        raise PipelineError(
            ErrorCode.INPUT_MISSING,
            f"{label} raster does not exist.",
            module=MODULE,
            details={"asset_id": asset.asset_id, "path": str(asset.path)},
        )
    spec = manifest.input_spec
    sensor_names = {asset.source_type.casefold(), asset.source.casefold()}
    if not any(sensor.casefold() in sensor_names for sensor in spec.sensors):
        raise _input_error(
            f"{label} source type is not supported by the model.",
            asset_id=asset.asset_id,
            source_type=asset.source_type,
            allowed_sensors=list(spec.sensors),
        )
    missing_bands = [band for band in spec.bands if band not in asset.bands]
    if missing_bands:
        raise _input_error(
            f"{label} is missing model bands.",
            asset_id=asset.asset_id,
            missing_bands=missing_bands,
        )
    if asset.pixel_size_m is None:
        raise _input_error(
            f"{label} has no pixel size.",
            asset_id=asset.asset_id,
        )
    if not spec.pixel_size_min_m <= asset.pixel_size_m <= spec.pixel_size_max_m:
        raise _input_error(
            f"{label} pixel size is outside model applicability.",
            asset_id=asset.asset_id,
            pixel_size_m=asset.pixel_size_m,
            minimum=spec.pixel_size_min_m,
            maximum=spec.pixel_size_max_m,
        )


def _validate_damage_features(
    collection: dict[str, Any],
    request: DamageRequest,
    manifest: ModelManifest,
    result: DamageResult,
) -> list[str]:
    errors: list[str] = []
    class_values = set(manifest.class_map.values())
    seen_ids: set[str] = set()
    for index, feature in enumerate(collection.get("features", [])):
        prefix = f"damage_vector.features[{index}]"
        properties = feature.get("properties", {})
        building_id = properties.get("building_id")
        if building_id in seen_ids:
            errors.append(f"{prefix}.building_id is duplicated")
        elif isinstance(building_id, str):
            seen_ids.add(building_id)
        expected = {
            "event_id": request.event_id,
            "study_area_id": request.study_area.identifier,
            "model_name": result.model_name,
            "model_version": result.model_version,
        }
        for field_name, value in expected.items():
            if properties.get(field_name) != value:
                errors.append(f"{prefix}.{field_name} must equal {value!r}")
        if properties.get("damage_class") not in class_values:
            errors.append(f"{prefix}.damage_class is not declared by class_map")
    return errors


def _validate_tile_features(
    collection: dict[str, Any],
    request: DamageRequest,
) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    for index, feature in enumerate(collection.get("features", [])):
        prefix = f"tile_index.features[{index}]"
        properties = feature.get("properties", {})
        tile_id = properties.get("tile_id")
        if tile_id in seen_ids:
            errors.append(f"{prefix}.tile_id is duplicated")
        elif isinstance(tile_id, str):
            seen_ids.add(tile_id)
        if properties.get("event_id") != request.event_id:
            errors.append(f"{prefix}.event_id must match the request")
        if properties.get("study_area_id") != request.study_area.identifier:
            errors.append(f"{prefix}.study_area_id must match the request")
    return errors


def _validate_metadata(path: Path, result: DamageResult) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_payload("ResultMeta", payload)
    except (OSError, json.JSONDecodeError, ContractValidationError, ValueError, TypeError) as exc:
        return [f"metadata cannot be validated: {exc}"]
    expected = to_payload(result.meta)
    identity_fields = (
        "schema_version",
        "event_id",
        "study_area_id",
        "input_asset_ids",
        "method",
        "method_version",
    )
    return [
        f"metadata.{field_name} differs from DamageResult.meta"
        for field_name in identity_fields
        if payload.get(field_name) != expected.get(field_name)
    ]


def _load_collection(
    path: Path,
    schema_name: str,
    properties: tuple[str, ...],
) -> tuple[list[str], dict[str, Any] | None]:
    try:
        if path.suffix.lower() in {".json", ".geojson"}:
            payload = json.loads(path.read_text(encoding="utf-8"))
        elif path.suffix.lower() == ".gpkg":
            return _load_gpkg_for_contract(path, schema_name, properties)
        else:
            return [f"{path.name}: unsupported vector artifact format"], None
        validate_payload(schema_name, payload)
        return [], payload
    except (
        OSError,
        json.JSONDecodeError,
        sqlite3.Error,
        ContractValidationError,
        ValueError,
        TypeError,
    ) as exc:
        return [f"{path.name}: {type(exc).__name__}: {exc}"], None


def _load_gpkg_for_contract(
    path: Path,
    schema_name: str,
    properties: tuple[str, ...],
) -> tuple[list[str], dict[str, Any] | None]:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        table_row = connection.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type = 'features' LIMIT 1"
        ).fetchone()
        if table_row is None:
            return ["GeoPackage has no feature table"], None
        table_name = str(table_row[0])
        columns = {
            str(row[1])
            for row in connection.execute(
                f'PRAGMA table_info("{_quote_identifier(table_name)}")'
            ).fetchall()
        }
        missing = [name for name in properties if name not in columns]
        if missing:
            return [f"GeoPackage is missing properties: {missing}"], None
        geometry_row = connection.execute(
            "SELECT column_name FROM gpkg_geometry_columns WHERE table_name = ? LIMIT 1",
            (table_name,),
        ).fetchone()
        if geometry_row is None:
            return ["GeoPackage has no geometry column metadata"], None
        geometry_column = str(geometry_row[0])
        if geometry_column not in columns:
            return ["GeoPackage geometry column is missing"], None
        select_columns = ", ".join(
            [f'"{_quote_identifier(name)}"' for name in properties]
            + [f'"{_quote_identifier(geometry_column)}"']
        )
        rows = connection.execute(
            f'SELECT {select_columns} FROM "{_quote_identifier(table_name)}"'
        ).fetchall()
    finally:
        connection.close()

    errors: list[str] = []
    features: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        geometry = row[-1]
        if geometry is None or not bytes(geometry):
            errors.append(f"GeoPackage feature {index} has no geometry")
        feature_properties = dict(zip(properties, row[:-1]))
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": []},
                "properties": feature_properties,
            }
        )
    payload = {"schema_version": "2.0", "type": "FeatureCollection", "features": features}
    try:
        validate_payload(schema_name, payload)
    except ContractValidationError as exc:
        errors.append(str(exc))
    return errors, payload


def _normalized_crs(value: str) -> str:
    return value.strip().casefold()


def _quote_identifier(value: str) -> str:
    return value.replace('"', '""')


def _input_error(message: str, **details: Any) -> PipelineError:
    return PipelineError(
        ErrorCode.INPUT_INVALID,
        message,
        module=MODULE,
        details=details,
    )
