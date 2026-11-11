"""用明确标注的合成样例检查适配器交接，不要求先训练模型。"""

from __future__ import annotations

import json
from dataclasses import dataclass

from remote_image.core.contracts import DamageModel, DamageRequest, DamageResult, InferenceOptions
from remote_image.core.validation import ContractValidationError, validate_contract, validate_payload


@dataclass(frozen=True)
class ContractTestReport:
    passed: bool
    checks: tuple[str, ...]
    errors: tuple[str, ...]


def validate_damage_response(
    request: DamageRequest, result: DamageResult, *, validate_artifacts: bool = True
) -> None:
    """校验请求和结果配对；生产交接默认检查实际小型产物。"""
    if not isinstance(result, DamageResult):
        raise ContractValidationError("predict must return DamageResult")
    validate_contract(request)
    validate_contract(result)
    if (result.model_name, result.model_version) != (request.model_name, request.model_version):
        raise ContractValidationError("模型名称或版本与请求不一致")
    if (result.meta.event_id, result.meta.study_area_id) != (
        request.event_id,
        request.study_area.identifier,
    ):
        raise ContractValidationError("结果事件或研究区与请求不一致")
    if result.meta.method != request.task:
        raise ContractValidationError("结果任务与请求不一致")
    expected_ids = {
        item.asset_id for item in (request.pre_event, request.post_event) if item is not None
    }
    if not expected_ids <= set(result.meta.input_asset_ids):
        raise ContractValidationError("结果缺少输入影像资产血缘")
    if not validate_artifacts:
        return
    for key, path in result.artifacts.items():
        if not path.is_file():
            raise ContractValidationError(f"产物不存在: {key}={path}")
        if key in ("damage_vector", "tile_index"):
            if path.suffix.lower() not in (".json", ".geojson"):
                raise ContractValidationError("核心契约测试仅直接读取 JSON/GeoJSON；GPKG 由 GIS 测试负责")
            validate_payload(key.replace("_", "-"), json.loads(path.read_text(encoding="utf-8")))
        elif key == "metadata":
            validate_payload("ResultMeta", json.loads(path.read_text(encoding="utf-8")))


def check_adapter_contract(
    adapter: DamageModel,
    fixture: DamageRequest,
    options: InferenceOptions | None = None,
    *,
    validate_artifacts: bool = True,
) -> ContractTestReport:
    """返回结构化检查结果；fixture 必须是隔离的合成样例。"""
    try:
        validate_contract(fixture)
        if options is not None:
            validate_contract(options)
        result = adapter.predict(fixture, options)
        validate_damage_response(fixture, result, validate_artifacts=validate_artifacts)
    except Exception as error:
        return ContractTestReport(False, (), (f"{type(error).__name__}: {error}",))
    checks = ("schema_v2", "model_identity", "event_and_area", "input_asset_ids", "task")
    if validate_artifacts:
        checks += ("artifact_files",)
    return ContractTestReport(True, checks, ())
