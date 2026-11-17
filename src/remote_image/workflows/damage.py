"""C1 第二阶段建筑灾损推理入口。"""

from __future__ import annotations

from pathlib import Path

from remote_image.core.contracts import (
    DamageModel,
    DamageRequest,
    DamageResult,
    InferenceOptions,
)
from remote_image.core.damage_runtime import default_damage_runtime


def load_model(manifest_path: Path, device: str = "cpu") -> DamageModel:
    """从独立模型清单加载并校验 DamageModel 适配器。"""

    return default_damage_runtime.load_model(manifest_path, device=device)


def register_model(name: str, adapter: DamageModel) -> None:
    """注册已加载的模型，供 run_damage 按名称调用。"""

    default_damage_runtime.register_model(name, adapter)


def run_damage(
    request: DamageRequest,
    options: InferenceOptions | None = None,
) -> DamageResult:
    """合并推理参数、调用适配器并执行请求/结果契约校验。"""

    return default_damage_runtime.run_damage(request, options=options)


__all__ = ["load_model", "register_model", "run_damage"]
