"""C1 公共编排边界。可直接实现的文件交接已落地，业务编排保留明确占位。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from remote_image.core.contracts import (
    LayerManifest, MapLayerSpec, PipelineConfig, PipelineRunResult, ResultEnvelope,
    ResultMeta, Stage, ValidationReport,
)
from remote_image.core.serialization import from_payload, to_payload
from remote_image.core.validation import ContractValidationError, validate_contract, validate_payload


def load_config(path: Path) -> PipelineConfig:
    return from_payload(PipelineConfig, json.loads(path.read_text(encoding="utf-8")))


def run_pipeline(config: PipelineConfig, stage: Stage) -> PipelineRunResult:
    validate_contract(config)
    if config.stage != stage:
        raise ContractValidationError("配置 stage 与调用 stage 不一致")
    raise NotImplementedError("C1: 在各岗位业务实现完成后按阶段注册编排")


def validate_result(result: ResultEnvelope, expected_schema: str) -> ValidationReport:
    from remote_image.core.contracts import CheckItem

    try:
        validate_payload(expected_schema, to_payload(result))
    except ValueError as error:
        return ValidationReport(
            status="fail",
            checks=(CheckItem("schema", "fail", expected_schema, type(result).__name__, str(error)),),
        )
    return ValidationReport(
        status="pass",
        checks=(CheckItem("schema", "pass", expected_schema, type(result).__name__, "契约通过"),),
    )


def write_metadata(meta: ResultMeta, path: Path) -> Path:
    validate_contract(meta)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_payload(meta), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def build_manifest(layers: Sequence[MapLayerSpec], event_id: str, output_path: Path) -> LayerManifest:
    manifest = LayerManifest(event_id=event_id, layers=tuple(layers))
    validate_contract(manifest)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(to_payload(manifest), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def run_stage3(config: PipelineConfig) -> PipelineRunResult:
    validate_contract(config)
    if config.stage != "stage3":
        raise ContractValidationError("run_stage3 只接受 stage3 配置")
    raise NotImplementedError("C1: 按 before、核查更新、after、比较的顺序编排")


def write_run_summary(result: PipelineRunResult, output_path: Path) -> Path:
    validate_contract(result)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(to_payload(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path
