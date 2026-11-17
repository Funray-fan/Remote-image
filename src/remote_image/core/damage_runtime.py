"""C1 第二阶段模型加载、注册和推理运行器。"""

from __future__ import annotations

import importlib
import json
import sqlite3
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from remote_image.core.contracts import (
    DamageModel,
    DamageRequest,
    DamageResult,
    InferenceOptions,
    ModelManifest,
)
from remote_image.core.errors import ErrorCode, PipelineError
from remote_image.core.model_manifest import (
    load_model_manifest,
    merge_inference_options,
    with_load_device,
)
from remote_image.core.validation import (
    ValidationReport,
    load_schema,
    validate_json,
)


MODULE = "workflows.damage"
_REGISTRATION_MODULE = "core.damage_runtime"


@dataclass(frozen=True)
class LoadedDamageModel:
    """携带模型清单的协议包装器，便于 run_damage 合并默认参数。"""

    name: str
    adapter: DamageModel
    manifest: ModelManifest

    def predict(
        self, request: DamageRequest, options: InferenceOptions | None = None
    ) -> DamageResult:
        return self.adapter.predict(request, options)


@dataclass(frozen=True)
class _Registration:
    adapter: DamageModel
    manifest: ModelManifest


class DamageRuntime:
    """按模型名称管理和运行 DamageModel 适配器。"""

    def __init__(self) -> None:
        self._models: dict[str, _Registration] = {}

    def load_model(self, manifest_path: Path, device: str = "cpu") -> DamageModel:
        try:
            manifest = load_model_manifest(Path(manifest_path))
            manifest = with_load_device(manifest, device)
            adapter = _instantiate_adapter(manifest)
            if not callable(getattr(adapter, "predict", None)):
                raise PipelineError(
                    ErrorCode.MODEL_LOAD_FAILED,
                    "适配器工厂返回值没有可调用的 predict 方法",
                    module=_REGISTRATION_MODULE,
                    details={"adapter_entrypoint": manifest.adapter_entrypoint},
                )
            adapter_name = getattr(adapter, "name", None)
            if adapter_name != manifest.model_name:
                raise PipelineError(
                    ErrorCode.MODEL_LOAD_FAILED,
                    "适配器 name 与模型清单不一致",
                    module=_REGISTRATION_MODULE,
                    details={
                        "adapter_name": adapter_name,
                        "manifest_model_name": manifest.model_name,
                    },
                )
            return LoadedDamageModel(
                name=manifest.model_name,
                adapter=adapter,
                manifest=manifest,
            )
        except PipelineError:
            raise
        except Exception as exc:  # noqa: BLE001 - stable public error boundary
            raise PipelineError(
                ErrorCode.MODEL_LOAD_FAILED,
                "加载 DamageModel 适配器失败",
                module=_REGISTRATION_MODULE,
                details={
                    "manifest_path": str(manifest_path),
                    "reason": f"{type(exc).__name__}: {exc}",
                },
            ) from exc

    def register_model(self, name: str, adapter: DamageModel) -> None:
        if not name or name.strip() != name:
            raise PipelineError(
                ErrorCode.INPUT_INVALID,
                "模型名称不能为空且不能含首尾空格",
                module=_REGISTRATION_MODULE,
            )
        if not callable(getattr(adapter, "predict", None)):
            raise PipelineError(
                ErrorCode.INPUT_INVALID,
                "适配器必须实现 predict 方法",
                module=_REGISTRATION_MODULE,
                details={"model_name": name},
            )
        if getattr(adapter, "name", None) != name:
            raise PipelineError(
                ErrorCode.INPUT_INVALID,
                "注册名称必须与适配器 name 一致",
                module=_REGISTRATION_MODULE,
                details={
                    "registered_name": name,
                    "adapter_name": getattr(adapter, "name", None),
                },
            )
        manifest = getattr(adapter, "manifest", None)
        if not isinstance(manifest, ModelManifest):
            raise PipelineError(
                ErrorCode.INPUT_INVALID,
                "适配器必须通过 load_model 携带 ModelManifest 后注册",
                module=_REGISTRATION_MODULE,
                details={"model_name": name},
            )
        if manifest.model_name != name:
            raise PipelineError(
                ErrorCode.INPUT_INVALID,
                "注册名称必须与模型清单一致",
                module=_REGISTRATION_MODULE,
                details={
                    "registered_name": name,
                    "manifest_model_name": manifest.model_name,
                },
            )
        if name in self._models:
            raise PipelineError(
                ErrorCode.INPUT_INVALID,
                "模型名称已注册",
                module=_REGISTRATION_MODULE,
                details={"model_name": name},
            )
        self._models[name] = _Registration(adapter=adapter, manifest=manifest)

    def run_damage(
        self,
        request: DamageRequest,
        options: InferenceOptions | None = None,
    ) -> DamageResult:
        registration = self._models.get(request.model_name)
        if registration is None:
            raise PipelineError(
                ErrorCode.MODEL_LOAD_FAILED,
                "请求的模型尚未加载和注册",
                module=MODULE,
                details={
                    "model_name": request.model_name,
                    "registered_models": sorted(self._models),
                },
            )

        effective_options = merge_inference_options(registration.manifest, options)
        request_payload = _damage_request_payload(request, effective_options)
        _validate_request(request, registration.manifest, request_payload)

        try:
            raw_result = registration.adapter.predict(request, effective_options)
        except PipelineError:
            raise
        except Exception as exc:  # noqa: BLE001 - map adapter failures to one code
            raise PipelineError(
                ErrorCode.PROCESSING_FAILED,
                "灾损模型推理失败",
                module=MODULE,
                details={
                    "model_name": request.model_name,
                    "reason": f"{type(exc).__name__}: {exc}",
                },
            ) from exc

        if not isinstance(raw_result, DamageResult):
            raise PipelineError(
                ErrorCode.PROCESSING_FAILED,
                "适配器必须返回 DamageResult",
                module=MODULE,
                details={"returned_type": type(raw_result).__name__},
            )

        parameters = dict(raw_result.meta.parameters)
        parameters["inference_options"] = asdict(effective_options)
        result = replace(
            raw_result,
            meta=replace(raw_result.meta, parameters=parameters),
        )
        result_report = validate_damage_result(result, request, registration.manifest)
        if not result_report.valid:
            raise PipelineError(
                ErrorCode.PROCESSING_FAILED,
                "DamageResult 未通过 C1 契约校验",
                module=MODULE,
                details={
                    "model_name": request.model_name,
                    "errors": list(result_report.errors),
                },
            )
        return result


def _instantiate_adapter(manifest: ModelManifest) -> DamageModel:
    module_name, separator, attribute = manifest.adapter_entrypoint.partition(":")
    if not separator or not module_name or not attribute:
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "adapter_entrypoint 必须使用 module:factory 格式",
            module=_REGISTRATION_MODULE,
            details={"adapter_entrypoint": manifest.adapter_entrypoint},
        )
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute, None)
    if not callable(factory):
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "adapter_entrypoint 未指向可调用工厂",
            module=_REGISTRATION_MODULE,
            details={"adapter_entrypoint": manifest.adapter_entrypoint},
        )
    return factory(manifest)


def validate_damage_result(
    result: DamageResult,
    request: DamageRequest,
    manifest: ModelManifest | None = None,
) -> ValidationReport:
    """校验 DamageResult、内嵌资产及请求一致性。"""

    errors: list[str] = []
    try:
        payload = _damage_result_payload(result)
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        return _report(f"result parameters are not JSON serializable: {exc}")

    schema_report = validate_json("damage-result.schema.json", payload)
    errors.extend(schema_report.errors)

    for artifact_name, artifact_path in result.artifacts.items():
        path = Path(artifact_path)
        if not path.is_file():
            errors.append(f"artifact {artifact_name} does not exist: {path}")

    errors.extend(_validate_nested_artifacts(result, request, manifest))
    errors.extend(_validate_result_identity(result, request, manifest))
    return _report(*errors)


def _validate_request(
    request: DamageRequest,
    manifest: ModelManifest,
    request_payload: dict[str, Any],
) -> None:
    report = validate_json("damage-request.schema.json", request_payload)
    if not report.valid:
        raise PipelineError(
            ErrorCode.INPUT_INVALID,
            "DamageRequest 未通过 schema 校验",
            module=MODULE,
            details={"errors": list(report.errors)},
        )
    if manifest.task != request.task:
        raise PipelineError(
            ErrorCode.INPUT_INVALID,
            "请求任务与模型清单任务不一致",
            module=MODULE,
            details={"request_task": request.task, "manifest_task": manifest.task},
        )
    if manifest.input_spec.pre_event_required and request.pre_event is None:
        raise PipelineError(
            ErrorCode.INPUT_MISSING,
            "模型要求灾前影像，但请求未提供",
            module=MODULE,
            details={"model_name": manifest.model_name},
        )
    for label, asset in (
        ("pre_event", request.pre_event),
        ("post_event", request.post_event),
    ):
        if asset is None:
            continue
        missing_bands = [
            band for band in manifest.input_spec.bands if band not in asset.bands
        ]
        if missing_bands:
            raise PipelineError(
                ErrorCode.INPUT_INVALID,
                f"{label} 缺少模型所需波段",
                module=MODULE,
                details={"asset_id": asset.asset_id, "missing_bands": missing_bands},
            )
        if asset.pixel_size_m is None:
            raise PipelineError(
                ErrorCode.INPUT_INVALID,
                f"{label} 缺少像元尺寸",
                module=MODULE,
                details={"asset_id": asset.asset_id},
            )
        if not (
            manifest.input_spec.pixel_size_m_min
            <= asset.pixel_size_m
            <= manifest.input_spec.pixel_size_m_max
        ):
            raise PipelineError(
                ErrorCode.INPUT_INVALID,
                f"{label} 像元尺寸超出模型适用范围",
                module=MODULE,
                details={
                    "asset_id": asset.asset_id,
                    "pixel_size_m": asset.pixel_size_m,
                    "minimum": manifest.input_spec.pixel_size_m_min,
                    "maximum": manifest.input_spec.pixel_size_m_max,
                },
            )


def _damage_request_payload(
    request: DamageRequest, options: InferenceOptions
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "event_id": request.event_id,
        "study_area_id": request.study_area.identifier,
        "post_event_asset_id": request.post_event.asset_id,
        "pre_event_asset_id": request.pre_event.asset_id if request.pre_event else None,
        "building_footprints": str(request.building_footprints)
        if request.building_footprints
        else None,
        "model_name": request.model_name,
        "task": request.task,
        "inference_options": asdict(options),
    }


def _damage_result_payload(result: DamageResult) -> dict[str, Any]:
    meta = result.meta
    return {
        "schema_version": meta.schema_version,
        "model_name": result.model_name,
        "model_version": result.model_version,
        "artifacts": {key: str(value) for key, value in result.artifacts.items()},
        "meta": {
            "schema_version": meta.schema_version,
            "event_id": meta.event_id,
            "study_area_id": meta.study_area_id,
            "input_asset_ids": list(meta.input_asset_ids),
            "method": meta.method,
            "method_version": meta.method_version,
            "parameters": meta.parameters,
            "created_at": _iso_datetime(meta.created_at),
            "warnings": list(meta.warnings),
        },
    }


def _iso_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _expected_asset_ids(request: DamageRequest) -> set[str]:
    return {
        asset.asset_id
        for asset in (request.pre_event, request.post_event)
        if asset is not None
    }


def _validate_result_identity(
    result: DamageResult,
    request: DamageRequest,
    manifest: ModelManifest | None,
) -> list[str]:
    errors: list[str] = []
    if result.model_name != request.model_name:
        errors.append("result.model_name must match request.model_name")
    if manifest and result.model_version != manifest.model_version:
        errors.append("result.model_version must match model manifest")
    if result.meta.event_id != request.event_id:
        errors.append("result.meta.event_id must match request.event_id")
    if result.meta.study_area_id != request.study_area.identifier:
        errors.append("result.meta.study_area_id must match request study area")
    if result.meta.method != request.task:
        errors.append("result.meta.method must match request.task")
    if set(result.meta.input_asset_ids) != _expected_asset_ids(request):
        errors.append("result.meta.input_asset_ids must match request assets")
    return errors


def _validate_nested_artifacts(
    result: DamageResult,
    request: DamageRequest,
    manifest: ModelManifest | None,
) -> list[str]:
    errors: list[str] = []
    damage_vector = result.artifacts.get("damage_vector")
    if damage_vector:
        collection_errors, collection = _validate_collection(
            Path(damage_vector), "damage-vector.schema.json"
        )
        errors.extend(collection_errors)
        if collection:
            for index, feature in enumerate(collection.get("features", [])):
                properties = feature.get("properties", {})
                prefix = f"damage_vector.features[{index}]"
                if properties.get("event_id") != request.event_id:
                    errors.append(f"{prefix}.event_id must match request.event_id")
                if properties.get("model_name") != result.model_name:
                    errors.append(f"{prefix}.model_name must match result.model_name")
                if properties.get("model_version") != result.model_version:
                    errors.append(
                        f"{prefix}.model_version must match result.model_version"
                    )

    tile_index = result.artifacts.get("tile_index")
    if tile_index:
        collection_errors, collection = _validate_collection(
            Path(tile_index), "tile-index.schema.json"
        )
        errors.extend(collection_errors)
        if collection:
            expected = _expected_asset_ids(request)
            for index, feature in enumerate(collection.get("features", [])):
                source_asset_id = feature.get("properties", {}).get("source_asset_id")
                if source_asset_id not in expected:
                    errors.append(
                        "tile_index.features[{}].source_asset_id must reference "
                        "request input assets".format(index)
                    )

    if manifest and damage_vector:
        class_values = set(manifest.class_map.values())
        if class_values:
            _, collection = _validate_collection(
                Path(damage_vector), "damage-vector.schema.json"
            )
            if collection:
                for index, feature in enumerate(collection.get("features", [])):
                    damage_class = feature.get("properties", {}).get("damage_class")
                    if damage_class not in class_values:
                        errors.append(
                            f"damage_vector.features[{index}].damage_class "
                            "is not declared by model manifest class_map"
                        )
    return errors


def _validate_collection(
    path: Path, schema_name: str
) -> tuple[list[str], dict[str, Any] | None]:
    if not path.is_file():
        return [], None
    try:
        collection = (
            _read_json(path)
            if path.suffix.lower() in {".json", ".geojson"}
            else _read_gpkg(path, schema_name)
        )
    except Exception as exc:  # noqa: BLE001 - reported as result contract failure
        return [f"{path.name} cannot be read: {type(exc).__name__}: {exc}"], None
    report = validate_json(schema_name, collection)
    return list(report.errors), collection


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("feature collection must be a JSON object")
    return payload


def _read_gpkg(path: Path, schema_name: str) -> dict[str, Any]:
    schema = load_schema(schema_name)
    property_names = set(
        schema["properties"]["features"]["items"]["properties"]["properties"][
            "properties"
        ]
    )
    connection = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro",
        uri=True,
    )
    try:
        table_row = connection.execute(
            "SELECT table_name FROM gpkg_contents "
            "WHERE data_type = 'features' LIMIT 1"
        ).fetchone()
        if not table_row:
            raise ValueError("GeoPackage contains no feature table")
        table_name = table_row[0]
        columns = [
            row[1]
            for row in connection.execute(
                f'PRAGMA table_info("{_quote_identifier(table_name)}")'
            ).fetchall()
        ]
        selected = [column for column in columns if column in property_names]
        if not selected:
            raise ValueError("GeoPackage feature table has no contract properties")
        select_sql = ", ".join(
            f'"{_quote_identifier(column)}"' for column in selected
        )
        rows = connection.execute(
            f'SELECT {select_sql} FROM "{_quote_identifier(table_name)}"'
        ).fetchall()
    finally:
        connection.close()

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": None,
                "properties": dict(zip(selected, row)),
            }
            for row in rows
        ],
    }


def _quote_identifier(value: str) -> str:
    return value.replace('"', '""')


def _report(*errors: str) -> ValidationReport:
    return ValidationReport(
        schema_name="damage-result+nested",
        errors=tuple(errors),
    )


default_damage_runtime = DamageRuntime()
