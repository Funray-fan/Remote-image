"""不依赖真实训练权重的灾损模型适配器契约检查。"""

from __future__ import annotations

from dataclasses import dataclass

from remote_image.core.contracts import (
    DamageModel,
    DamageRequest,
    DamageResult,
    InferenceOptions,
)


@dataclass(frozen=True)
class ContractTestReport:
    passed: bool
    checks: tuple[str, ...]
    errors: tuple[str, ...]


def check_adapter_contract(
    adapter: DamageModel,
    fixture: DamageRequest,
    options: InferenceOptions | None = None,
) -> ContractTestReport:
    """检查适配器返回的对象形状，不评价模型精度。

    fixture 应指向隔离的合成样例。真实模型、权重和训练结果不是本检查的前提。
    """

    checks: list[str] = []
    errors: list[str] = []
    try:
        result = adapter.predict(fixture, options)
    except Exception as exc:  # noqa: BLE001 - report adapter boundary failures
        return ContractTestReport(False, (), (f"predict raised {type(exc).__name__}: {exc}",))

    if not isinstance(result, DamageResult):
        errors.append("predict must return DamageResult")
        return ContractTestReport(False, tuple(checks), tuple(errors))
    checks.append("return_type")

    allowed = {"damage_vector", "damage_mask", "building_mask", "tile_index", "metadata"}
    unknown = set(result.artifacts) - allowed
    if unknown:
        errors.append(f"unknown artifact keys: {sorted(unknown)}")
    if "metadata" not in result.artifacts:
        errors.append("artifacts must include metadata")
    if "tile_index" not in result.artifacts:
        errors.append("artifacts must include tile_index")
    if not ({"damage_vector", "damage_mask", "building_mask"} & set(result.artifacts)):
        errors.append("artifacts must include a damage or building result")
    if not errors:
        checks.append("artifact_keys")

    if result.meta.event_id != fixture.event_id:
        errors.append("result meta.event_id must match request.event_id")
    else:
        checks.append("event_id")
    if result.meta.study_area_id != fixture.study_area.identifier:
        errors.append("result meta.study_area_id must match request.study_area.identifier")
    else:
        checks.append("study_area_id")
    if fixture.post_event.asset_id not in result.meta.input_asset_ids:
        errors.append("post_event asset_id must appear in ResultMeta.input_asset_ids")
    else:
        checks.append("input_asset_ids")
    if not result.model_name or not result.model_version:
        errors.append("model_name and model_version are required")
    else:
        checks.append("model_identity")

    return ContractTestReport(not errors, tuple(checks), tuple(errors))
