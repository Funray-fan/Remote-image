"""Load and validate the v2 model package manifest."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any

from remote_image.core.contracts import InferenceLimits, InferenceOptions, ModelManifest
from remote_image.core.errors import ErrorCode, PipelineError
from remote_image.core.serialization import from_payload
from remote_image.core.validation import ContractValidationError, validate_payload


MODULE = "core.model_manifest"
_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")


def load_model_manifest(
    manifest_path: str | Path,
    *,
    project_root: str | Path | None = None,
) -> ModelManifest:
    """Read a v2 manifest and resolve local model package paths safely."""

    path = Path(manifest_path)
    if not path.is_file():
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "Model manifest does not exist.",
            module=MODULE,
            details={"manifest_path": str(path)},
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_payload("ModelManifest", payload)
        manifest = from_payload(ModelManifest, payload)
    except (OSError, json.JSONDecodeError, ContractValidationError, ValueError, TypeError) as exc:
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "Model manifest is not a valid v2 contract.",
            module=MODULE,
            details={"manifest_path": str(path), "reason": str(exc)},
        ) from exc

    root = _resolve_project_root(path, project_root)
    weights_path = _resolve_project_file(root, manifest.weights_path, field="weights_path")
    evaluation_path = _resolve_project_file(
        root, manifest.evaluation_path, field="evaluation_path"
    )
    manifest = replace(
        manifest,
        weights_path=weights_path,
        evaluation_path=evaluation_path,
    )
    _validate_manifest_semantics(manifest)
    _validate_weight(manifest)
    return manifest


def with_load_device(manifest: ModelManifest, device: str) -> ModelManifest:
    """Return a manifest whose default device is the requested load device."""

    device = device.strip() if isinstance(device, str) else ""
    if not device:
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "Load device must be a non-empty string.",
            module=MODULE,
        )
    limits = manifest.inference_limits
    if not _device_allowed(device, limits.allowed_devices):
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "The model does not allow the requested load device.",
            module=MODULE,
            details={"device": device, "allowed_devices": list(limits.allowed_devices)},
        )
    return replace(
        manifest,
        inference_defaults=replace(manifest.inference_defaults, device=device),
    )


def merge_inference_options(
    manifest: ModelManifest,
    overrides: InferenceOptions | None,
) -> InferenceOptions:
    """Merge manifest defaults, request overrides, and the input tile size."""

    defaults = manifest.inference_defaults
    request = overrides or InferenceOptions()
    values: dict[str, Any] = {}
    for field_name in (
        "tile_size_px",
        "overlap_ratio",
        "confidence_threshold",
        "device",
        "batch_size",
    ):
        override = getattr(request, field_name)
        values[field_name] = override if override is not None else getattr(defaults, field_name)
    if values["tile_size_px"] is None:
        values["tile_size_px"] = manifest.input_spec.tile_size_px
    merged = InferenceOptions(**values)
    validate_inference_options(merged, manifest.inference_limits)
    return merged


def validate_inference_options(
    options: InferenceOptions,
    limits: InferenceLimits,
) -> None:
    """Validate effective inference values against model hard limits."""

    numeric_fields = (
        ("tile_size_px", options.tile_size_px),
        ("overlap_ratio", options.overlap_ratio),
        ("confidence_threshold", options.confidence_threshold),
        ("batch_size", options.batch_size),
    )
    for field_name, value in numeric_fields:
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _input_error(field_name, value, "must be numeric")

    tile_size = options.tile_size_px
    if tile_size is None:
        raise _input_error("tile_size_px", None, "must be resolved before inference")
    if not isinstance(tile_size, int) or isinstance(tile_size, bool) or tile_size <= 0:
        raise _input_error("tile_size_px", tile_size, "must be a positive integer")
    if tile_size < limits.tile_size_min_px:
        raise _limit_error("tile_size_px", tile_size, limits.tile_size_min_px, limits.tile_size_max_px)
    if limits.tile_size_max_px is not None and tile_size > limits.tile_size_max_px:
        raise _limit_error("tile_size_px", tile_size, limits.tile_size_min_px, limits.tile_size_max_px)
    if limits.allowed_tile_sizes_px and tile_size not in limits.allowed_tile_sizes_px:
        raise PipelineError(
            ErrorCode.INPUT_INVALID,
            "tile_size_px is not in the allowed tile sizes.",
            module=MODULE,
            details={"value": tile_size, "allowed": list(limits.allowed_tile_sizes_px)},
        )

    if options.overlap_ratio is not None:
        overlap = float(options.overlap_ratio)
        if not 0 <= overlap <= limits.overlap_ratio_max:
            raise PipelineError(
                ErrorCode.INPUT_INVALID,
                "overlap_ratio is outside the model limits.",
                module=MODULE,
                details={"value": overlap, "minimum": 0.0, "maximum": limits.overlap_ratio_max},
            )

    if options.confidence_threshold is not None:
        confidence = float(options.confidence_threshold)
        if not limits.confidence_threshold_min <= confidence <= limits.confidence_threshold_max:
            raise PipelineError(
                ErrorCode.INPUT_INVALID,
                "confidence_threshold is outside the model limits.",
                module=MODULE,
                details={
                    "value": confidence,
                    "minimum": limits.confidence_threshold_min,
                    "maximum": limits.confidence_threshold_max,
                },
            )

    if options.batch_size is not None:
        batch_size = options.batch_size
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size <= 0:
            raise _input_error("batch_size", batch_size, "must be a positive integer")
        if limits.batch_size_max is not None and batch_size > limits.batch_size_max:
            raise _limit_error("batch_size", batch_size, 1, limits.batch_size_max)

    device = options.device
    if device is not None and not _device_allowed(device, limits.allowed_devices):
        raise PipelineError(
            ErrorCode.INPUT_INVALID,
            "device is not allowed by the model manifest.",
            module=MODULE,
            details={"device": device, "allowed_devices": list(limits.allowed_devices)},
        )


def _validate_manifest_semantics(manifest: ModelManifest) -> None:
    spec = manifest.input_spec
    limits = manifest.inference_limits
    errors: list[str] = []
    if not manifest.model_name.strip() or not manifest.model_version.strip():
        errors.append("model_name and model_version must be non-empty")
    if not spec.sensors or not spec.bands:
        errors.append("input_spec.sensors and input_spec.bands must be non-empty")
    if not 0 < spec.pixel_size_min_m <= spec.pixel_size_max_m:
        errors.append("input_spec pixel-size range is invalid")
    if spec.tile_size_px <= 0:
        errors.append("input_spec.tile_size_px must be positive")
    if not manifest.class_map:
        errors.append("class_map must be non-empty")
    if manifest.class_map != manifest.object_aggregation.damage_class_map:
        errors.append("class_map must equal object_aggregation.damage_class_map")
    if limits.tile_size_min_px <= 0:
        errors.append("inference_limits.tile_size_min_px must be positive")
    if limits.tile_size_max_px is not None and limits.tile_size_max_px < limits.tile_size_min_px:
        errors.append("inference_limits tile-size range is inverted")
    if any(value <= 0 for value in limits.allowed_tile_sizes_px):
        errors.append("allowed_tile_sizes_px values must be positive")
    if any(
        value < limits.tile_size_min_px
        or (limits.tile_size_max_px is not None and value > limits.tile_size_max_px)
        for value in limits.allowed_tile_sizes_px
    ):
        errors.append("allowed_tile_sizes_px values must be inside the tile-size range")
    if not 0 <= limits.overlap_ratio_max < 1:
        errors.append("overlap_ratio_max must be in [0, 1)")
    if not 0 <= limits.confidence_threshold_min <= limits.confidence_threshold_max <= 1:
        errors.append("confidence threshold limits are invalid")
    if not limits.allowed_devices:
        errors.append("allowed_devices must be non-empty")
    if limits.batch_size_max is not None and limits.batch_size_max <= 0:
        errors.append("batch_size_max must be positive or null")
    if errors:
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "Model manifest contains invalid semantic values.",
            module=MODULE,
            details={"errors": errors},
        )

    defaults = manifest.inference_defaults
    if defaults.tile_size_px is None:
        defaults = replace(defaults, tile_size_px=spec.tile_size_px)
    try:
        validate_inference_options(defaults, limits)
    except PipelineError as exc:
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "Model manifest defaults violate inference limits.",
            module=MODULE,
            details={"cause": exc.to_dict()},
        ) from exc


def _validate_weight(manifest: ModelManifest) -> None:
    if not _SHA256.fullmatch(manifest.weights_sha256):
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "weights_sha256 must contain 64 hexadecimal characters.",
            module=MODULE,
        )
    digest = hashlib.sha256()
    with manifest.weights_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual.lower() != manifest.weights_sha256.lower():
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "Model weight SHA-256 mismatch.",
            module=MODULE,
            details={
                "weights_path": str(manifest.weights_path),
                "expected_sha256": manifest.weights_sha256.lower(),
                "actual_sha256": actual,
            },
        )


def _resolve_project_root(manifest_path: Path, project_root: str | Path | None) -> Path:
    if project_root is not None:
        return Path(project_root).resolve()
    for parent in manifest_path.resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd().resolve()


def _resolve_project_file(root: Path, value: Path, *, field: str) -> Path:
    raw = value.as_posix()
    pure = PurePosixPath(raw)
    if pure.is_absolute() or ".." in pure.parts or ":" in raw or "\\" in raw:
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            f"{field} must be a project-relative path.",
            module=MODULE,
            details={"field": field, "value": raw},
        )
    resolved = (root / raw).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            f"{field} escapes the project directory.",
            module=MODULE,
            details={"field": field, "value": raw},
        ) from exc
    if not resolved.is_file():
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            f"{field} does not reference an existing file.",
            module=MODULE,
            details={"field": field, "path": str(resolved)},
        )
    return resolved


def _device_allowed(device: str, allowed_devices: tuple[str, ...]) -> bool:
    return device in allowed_devices or any(
        device.startswith(f"{allowed}:") for allowed in allowed_devices
    )


def _input_error(field: str, value: Any, reason: str) -> PipelineError:
    return PipelineError(
        ErrorCode.INPUT_INVALID,
        f"{field} is invalid.",
        module=MODULE,
        details={"field": field, "value": value, "reason": reason},
    )


def _limit_error(field: str, value: Any, minimum: int | float | None, maximum: int | float | None) -> PipelineError:
    return PipelineError(
        ErrorCode.INPUT_INVALID,
        f"{field} is outside the model limits.",
        module=MODULE,
        details={"field": field, "value": value, "minimum": minimum, "maximum": maximum},
    )
