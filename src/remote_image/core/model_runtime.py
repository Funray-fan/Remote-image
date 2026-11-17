"""C1 model loading, versioned registration, and damage inference runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable

from remote_image.core.contracts import (
    DamageModel,
    DamageRequest,
    DamageResult,
    InferenceOptions,
    ModelManifest,
)
from remote_image.core.damage_validation import (
    validate_damage_output,
    validate_request_for_manifest,
)
from remote_image.core.errors import ErrorCode, PipelineError
from remote_image.core.model_manifest import (
    load_model_manifest,
    merge_inference_options,
    with_load_device,
)
from remote_image.core.registry import VersionedPluginRegistry
from remote_image.core.validation import ContractValidationError, validate_contract
from remote_image.modules.damage.contract_check import validate_damage_response


MODULE = "core.model_runtime"
ModelLoader = Callable[[ModelManifest, str], DamageModel]


@dataclass(frozen=True)
class LoadedDamageModel:
    """A DamageModel wrapper that keeps the validated model manifest."""

    name: str
    version: str
    adapter: DamageModel
    manifest: ModelManifest

    def predict(
        self,
        request: DamageRequest,
        options: InferenceOptions | None = None,
    ) -> DamageResult:
        return self.adapter.predict(request, options)


@dataclass(frozen=True)
class _Registration:
    adapter: DamageModel
    manifest: ModelManifest | None


class DamageRuntime:
    """Manage model loaders and registered name/version adapters."""

    def __init__(self, *, project_root: str | Path | None = None) -> None:
        self.project_root = Path(project_root).resolve() if project_root is not None else None
        self._loaders: dict[tuple[str, str], ModelLoader] = {}
        self._models = VersionedPluginRegistry()

    def register_model_loader(
        self,
        name: str,
        version: str,
        loader: ModelLoader,
    ) -> None:
        """Register the C2-owned factory that loads one model package."""

        key = _identity(name, version, code=ErrorCode.INPUT_INVALID)
        if not callable(loader):
            raise PipelineError(
                ErrorCode.INPUT_INVALID,
                "Model loader must be callable.",
                module=MODULE,
                details={"model_name": key[0], "model_version": key[1]},
            )
        if key in self._loaders:
            raise PipelineError(
                ErrorCode.INPUT_INVALID,
                "A loader is already registered for this model identity.",
                module=MODULE,
                details={"model_name": key[0], "model_version": key[1]},
            )
        self._loaders[key] = loader

    def load_model(
        self,
        manifest_path: str | Path,
        device: str = "cpu",
    ) -> DamageModel:
        """Load a validated manifest and construct its C2 adapter."""

        try:
            manifest = load_model_manifest(manifest_path, project_root=self.project_root)
            manifest = with_load_device(manifest, device)
            key = (manifest.model_name, manifest.model_version)
            loader = self._loaders.get(key)
            if loader is None:
                raise PipelineError(
                    ErrorCode.MODEL_LOAD_FAILED,
                    "No C2 model loader is registered for the manifest identity.",
                    module=MODULE,
                    details={
                        "model_name": manifest.model_name,
                        "model_version": manifest.model_version,
                        "registered_loaders": [
                            {"model_name": name, "model_version": version}
                            for name, version in sorted(self._loaders)
                        ],
                    },
                )
            adapter = loader(manifest, device)
            _validate_adapter_identity(
                adapter,
                manifest.model_name,
                manifest.model_version,
                code=ErrorCode.MODEL_LOAD_FAILED,
            )
            return LoadedDamageModel(
                name=manifest.model_name,
                version=manifest.model_version,
                adapter=adapter,
                manifest=manifest,
            )
        except PipelineError:
            raise
        except Exception as exc:
            raise PipelineError(
                ErrorCode.MODEL_LOAD_FAILED,
                "The C2 model loader failed.",
                module=MODULE,
                details={
                    "manifest_path": str(manifest_path),
                    "reason": f"{type(exc).__name__}: {exc}",
                },
            ) from exc

    def register_model(self, name: str, version: str, adapter: DamageModel) -> None:
        """Register an adapter by immutable model name and version."""

        key = _identity(name, version, code=ErrorCode.INPUT_INVALID)
        _validate_adapter_identity(adapter, key[0], key[1], code=ErrorCode.INPUT_INVALID)
        manifest = getattr(adapter, "manifest", None)
        if manifest is not None:
            if not isinstance(manifest, ModelManifest):
                raise PipelineError(
                    ErrorCode.INPUT_INVALID,
                    "adapter.manifest must be a ModelManifest.",
                    module=MODULE,
                )
            if (manifest.model_name, manifest.model_version) != key:
                raise PipelineError(
                    ErrorCode.INPUT_INVALID,
                    "Adapter manifest identity does not match registration identity.",
                    module=MODULE,
                    details={"model_name": key[0], "model_version": key[1]},
                )
        try:
            self._models.register(key[0], key[1], _Registration(adapter, manifest))
        except ValueError as exc:
            raise PipelineError(
                ErrorCode.INPUT_INVALID,
                "Model version is already registered.",
                module=MODULE,
                details={"model_name": key[0], "model_version": key[1], "reason": str(exc)},
            ) from exc

    def run_damage(
        self,
        request: DamageRequest,
        options: InferenceOptions | None = None,
    ) -> DamageResult:
        """Merge options, execute the exact model version, and validate handoff."""

        try:
            validate_contract(request)
            if options is not None:
                validate_contract(options)
        except ContractValidationError as exc:
            raise PipelineError(
                ErrorCode.INPUT_INVALID,
                "DamageRequest or InferenceOptions violates the v2 contract.",
                module=MODULE,
                details={"reason": str(exc)},
            ) from exc

        try:
            registration = self._models.get(
                request.model_name,
                request.model_version,
                expected_type=_Registration,
            )
        except (KeyError, TypeError) as exc:
            raise PipelineError(
                ErrorCode.MODEL_NOT_REGISTERED,
                "The requested model version is not registered.",
                module=MODULE,
                details={
                    "model_name": request.model_name,
                    "model_version": request.model_version,
                    "reason": str(exc),
                },
            ) from exc

        effective_options = options
        if registration.manifest is not None:
            validate_request_for_manifest(request, registration.manifest)
            effective_options = merge_inference_options(registration.manifest, options)

        try:
            raw_result = registration.adapter.predict(request, effective_options)
        except PipelineError:
            raise
        except Exception as exc:
            raise PipelineError(
                ErrorCode.PROCESSING_FAILED,
                "Damage model inference failed.",
                module=MODULE,
                details={
                    "model_name": request.model_name,
                    "model_version": request.model_version,
                    "reason": f"{type(exc).__name__}: {exc}",
                },
            ) from exc

        if not isinstance(raw_result, DamageResult):
            raise PipelineError(
                ErrorCode.RESULT_INVALID,
                "DamageModel.predict must return DamageResult.",
                module=MODULE,
                details={"returned_type": type(raw_result).__name__},
            )

        result = raw_result
        if registration.manifest is not None and effective_options is not None:
            parameters = dict(result.meta.parameters)
            parameters["inference_options"] = asdict(effective_options)
            result = replace(
                result,
                meta=replace(result.meta, parameters=parameters),
            )
            report = validate_damage_output(request, registration.manifest, result)
            if not report.valid:
                raise PipelineError(
                    ErrorCode.RESULT_INVALID,
                    "DamageResult failed C1 handoff validation.",
                    module=MODULE,
                    details={"errors": list(report.errors)},
                )
        else:
            try:
                validate_damage_response(request, result, validate_artifacts=False)
            except (ContractValidationError, ValueError, TypeError) as exc:
                raise PipelineError(
                    ErrorCode.RESULT_INVALID,
                    "DamageResult failed v2 contract validation.",
                    module=MODULE,
                    details={"reason": str(exc)},
                ) from exc
            missing_files = [
                f"{name}={path}"
                for name, path in result.artifacts.items()
                if not path.is_file()
            ]
            if missing_files:
                raise PipelineError(
                    ErrorCode.RESULT_INVALID,
                    "DamageResult references missing artifact files.",
                    module=MODULE,
                    details={"missing_files": missing_files},
                )
        return result


def _identity(name: str, version: str, *, code: ErrorCode) -> tuple[str, str]:
    if not isinstance(name, str) or not name or name.strip() != name:
        raise PipelineError(
            code,
            "model_name must be non-empty without surrounding whitespace.",
            module=MODULE,
        )
    if not isinstance(version, str) or not version or version.strip() != version:
        raise PipelineError(
            code,
            "model_version must be non-empty without surrounding whitespace.",
            module=MODULE,
        )
    return name, version


def _validate_adapter_identity(
    adapter: DamageModel,
    name: str,
    version: str,
    *,
    code: ErrorCode,
) -> None:
    if not callable(getattr(adapter, "predict", None)):
        raise PipelineError(
            code,
            "DamageModel adapter must provide predict().",
            module=MODULE,
            details={"model_name": name, "model_version": version},
        )
    actual = (getattr(adapter, "name", None), getattr(adapter, "version", None))
    if actual != (name, version):
        raise PipelineError(
            code,
            "Adapter identity does not match the requested model identity.",
            module=MODULE,
            details={
                "expected": {"model_name": name, "model_version": version},
                "actual": {"model_name": actual[0], "model_version": actual[1]},
            },
        )


default_damage_runtime = DamageRuntime()

load_model = default_damage_runtime.load_model
register_model = default_damage_runtime.register_model
register_model_loader = default_damage_runtime.register_model_loader
run_damage = default_damage_runtime.run_damage
