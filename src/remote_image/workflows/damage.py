"""Public C1 Stage 2 damage workflow entry points."""

from __future__ import annotations

from pathlib import Path

from remote_image.core.contracts import DamageModel, DamageRequest, DamageResult, InferenceOptions
from remote_image.core.model_runtime import default_damage_runtime
from remote_image.core.model_runtime import ModelLoader


def register_model_loader(name: str, version: str, loader: ModelLoader) -> None:
    """Register the C2 factory that can load one manifest/weight package."""

    default_damage_runtime.register_model_loader(name, version, loader)


def load_model(manifest_path: str | Path, device: str = "cpu") -> DamageModel:
    """Load a validated model manifest through its registered C2 factory."""

    return default_damage_runtime.load_model(manifest_path, device=device)


def register_model(name: str, version: str, adapter: DamageModel) -> None:
    """Register a loaded or manually constructed model adapter."""

    default_damage_runtime.register_model(name, version, adapter)


def run_damage(
    request: DamageRequest,
    options: InferenceOptions | None = None,
) -> DamageResult:
    """Run a registered model and validate the Stage 2 handoff."""

    return default_damage_runtime.run_damage(request, options=options)


__all__ = ["load_model", "register_model", "register_model_loader", "run_damage"]
