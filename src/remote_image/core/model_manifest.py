"""模型清单读取、权重校验和推理参数合并。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any

from remote_image.core.contracts import (
    InferenceOptions,
    ModelInputSpec,
    ModelManifest,
    ModelWeight,
)
from remote_image.core.errors import ErrorCode, PipelineError
from remote_image.core.validation import ValidationReport, validate_json


MODULE = "core.model_manifest"


def load_model_manifest(manifest_path: Path) -> ModelManifest:
    """读取、校验并解析独立的 model_manifest.json。"""

    path = Path(manifest_path)
    if not path.is_file():
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "模型清单不存在",
            module=MODULE,
            details={"manifest_path": str(path)},
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "模型清单无法读取或不是合法 JSON",
            module=MODULE,
            details={"manifest_path": str(path), "reason": str(exc)},
        ) from exc

    report = validate_json("model-manifest.schema.json", payload)
    _raise_invalid_manifest(report, path)

    weights = tuple(
        ModelWeight(
            path=_resolve_project_path(path, item["path"]),
            sha256=item["sha256"].lower(),
        )
        for item in payload["weights"]
    )
    for weight in weights:
        _validate_weight(path, weight)

    input_payload = payload["input"]
    input_spec = ModelInputSpec(
        bands=tuple(input_payload["bands"]),
        pre_event_required=input_payload["pre_event_required"],
        pixel_size_m_min=float(input_payload["pixel_size_m"]["min"]),
        pixel_size_m_max=float(input_payload["pixel_size_m"]["max"]),
        normalization_method=input_payload["normalization"]["method"],
        normalization_parameters=dict(input_payload["normalization"]["parameters"]),
    )
    if input_spec.pixel_size_m_min > input_spec.pixel_size_m_max:
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "模型清单的像元尺寸范围无效",
            module=MODULE,
            details={"manifest_path": str(path)},
        )

    defaults_payload = payload["inference_defaults"]
    defaults = InferenceOptions(**defaults_payload)
    manifest = ModelManifest(
        schema_version=payload["schema_version"],
        model_name=payload["model_name"],
        model_version=payload["model_version"],
        task=payload["task"],
        adapter_entrypoint=payload["adapter_entrypoint"],
        weights=weights,
        input_spec=input_spec,
        inference_defaults=defaults,
        inference_limits=dict(payload["inference_limits"]),
        class_map={int(code): name for code, name in payload["class_map"].items()},
        dependencies=dict(payload["dependencies"]),
        license_id=payload["license_id"],
        manifest_path=path.resolve(),
    )
    try:
        _validate_effective_options(defaults, manifest.inference_limits)
    except PipelineError as exc:
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "模型清单默认推理参数不合法",
            module=MODULE,
            details={"manifest_path": str(path), "cause": exc.to_dict()},
        ) from exc
    return manifest


def with_load_device(manifest: ModelManifest, device: str) -> ModelManifest:
    """将加载设备写入默认推理参数，并检查模型声明的设备范围。"""

    if not device or not device.strip():
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "device 不能为空",
            module=MODULE,
        )
    if not _device_allowed(device, manifest.inference_limits):
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "模型不支持指定设备",
            module=MODULE,
            details={
                "device": device,
                "allowed_devices": manifest.inference_limits["allowed_devices"],
            },
        )
    defaults = replace(manifest.inference_defaults, device=device)
    return replace(manifest, inference_defaults=defaults)


def merge_inference_options(
    manifest: ModelManifest,
    overrides: InferenceOptions | None = None,
) -> InferenceOptions:
    """按 manifest defaults -> request overrides 合并并检查硬限制。"""

    defaults = manifest.inference_defaults
    supplied = overrides or InferenceOptions()
    merged = InferenceOptions(
        tile_size_px=supplied.tile_size_px
        if supplied.tile_size_px is not None
        else defaults.tile_size_px,
        overlap_ratio=supplied.overlap_ratio
        if supplied.overlap_ratio is not None
        else defaults.overlap_ratio,
        confidence_threshold=supplied.confidence_threshold
        if supplied.confidence_threshold is not None
        else defaults.confidence_threshold,
        device=supplied.device if supplied.device is not None else defaults.device,
        batch_size=supplied.batch_size
        if supplied.batch_size is not None
        else defaults.batch_size,
    )
    _validate_effective_options(merged, manifest.inference_limits)
    return merged


def _validate_effective_options(
    options: InferenceOptions,
    limits: dict[str, Any],
) -> None:
    if isinstance(options.tile_size_px, bool) or not isinstance(
        options.tile_size_px, int
    ):
        raise PipelineError(
            ErrorCode.INPUT_INVALID,
            "tile_size_px 必须为整数",
            module=MODULE,
        )
    if isinstance(options.batch_size, bool) or not isinstance(
        options.batch_size, int
    ):
        raise PipelineError(
            ErrorCode.INPUT_INVALID,
            "batch_size 必须为整数",
            module=MODULE,
        )
    for field_name, value in (
        ("overlap_ratio", options.overlap_ratio),
        ("confidence_threshold", options.confidence_threshold),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PipelineError(
                ErrorCode.INPUT_INVALID,
                f"{field_name} 必须为数值",
                module=MODULE,
                details={"field": field_name, "value": value},
            )
    if not isinstance(options.device, str) or not options.device:
        raise PipelineError(
            ErrorCode.INPUT_INVALID,
            "device 必须为非空字符串",
            module=MODULE,
            details={"device": options.device},
        )

    checks = (
        ("tile_size_px", options.tile_size_px, limits["tile_size_px"]),
        ("overlap_ratio", options.overlap_ratio, limits["overlap_ratio"]),
        (
            "confidence_threshold",
            options.confidence_threshold,
            limits["confidence_threshold"],
        ),
        ("batch_size", options.batch_size, limits["batch_size"]),
    )
    for field_name, value, bounds in checks:
        if value < bounds["min"] or value > bounds["max"]:
            raise PipelineError(
                ErrorCode.INPUT_INVALID,
                f"推理参数 {field_name} 超出模型硬限制",
                module=MODULE,
                details={
                    "field": field_name,
                    "value": value,
                    "minimum": bounds["min"],
                    "maximum": bounds["max"],
                },
            )

    if options.tile_size_px <= 0:
        raise PipelineError(
            ErrorCode.INPUT_INVALID,
            "tile_size_px 必须为正整数",
            module=MODULE,
        )
    if not 0 <= options.overlap_ratio < 1:
        raise PipelineError(
            ErrorCode.INPUT_INVALID,
            "overlap_ratio 必须满足 0 <= value < 1",
            module=MODULE,
        )
    if not 0 <= options.confidence_threshold <= 1:
        raise PipelineError(
            ErrorCode.INPUT_INVALID,
            "confidence_threshold 必须位于 [0, 1]",
            module=MODULE,
        )
    if options.batch_size <= 0:
        raise PipelineError(
            ErrorCode.INPUT_INVALID,
            "batch_size 必须为正整数",
            module=MODULE,
        )
    if not _device_allowed(options.device, limits):
        raise PipelineError(
            ErrorCode.INPUT_INVALID,
            "推理设备不在模型允许范围内",
            module=MODULE,
            details={
                "device": options.device,
                "allowed_devices": limits["allowed_devices"],
            },
        )


def _device_allowed(device: str, limits: dict[str, Any]) -> bool:
    allowed = tuple(str(item) for item in limits["allowed_devices"])
    return device in allowed or any(device.startswith(f"{item}:") for item in allowed)


def _resolve_project_path(manifest_path: Path, raw_path: str) -> Path:
    pure = PurePosixPath(raw_path)
    if (
        pure.is_absolute()
        or ".." in pure.parts
        or ":" in raw_path
        or "\\" in raw_path
    ):
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "模型权重路径必须是项目内相对路径",
            module=MODULE,
            details={"manifest_path": str(manifest_path), "weight_path": raw_path},
        )

    project_candidate = (Path.cwd() / raw_path).resolve()
    if project_candidate.is_file():
        return project_candidate
    manifest_candidate = (manifest_path.parent / raw_path).resolve()
    return manifest_candidate


def _validate_weight(manifest_path: Path, weight: ModelWeight) -> None:
    if not weight.path.is_file():
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "模型权重文件不存在",
            module=MODULE,
            details={
                "manifest_path": str(manifest_path),
                "weight_path": str(weight.path),
            },
        )
    digest = hashlib.sha256()
    with weight.path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest().lower()
    if actual != weight.sha256:
        raise PipelineError(
            ErrorCode.MODEL_LOAD_FAILED,
            "模型权重 SHA-256 校验失败",
            module=MODULE,
            details={
                "manifest_path": str(manifest_path),
                "weight_path": str(weight.path),
                "expected_sha256": weight.sha256,
                "actual_sha256": actual,
            },
        )


def _raise_invalid_manifest(report: ValidationReport, manifest_path: Path) -> None:
    if report.valid:
        return
    raise PipelineError(
        ErrorCode.MODEL_LOAD_FAILED,
        "模型清单不符合 model-manifest.schema.json",
        module=MODULE,
        details={"manifest_path": str(manifest_path), "errors": list(report.errors)},
    )
