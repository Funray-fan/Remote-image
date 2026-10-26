"""C1 模型版本注册与推理入口。权重加载由 C2 提供的适配器完成。"""

from remote_image.core.contracts import DamageModel, DamageRequest, DamageResult, InferenceOptions
from remote_image.core.registry import VersionedPluginRegistry
from remote_image.core.validation import ContractValidationError, validate_contract
from remote_image.modules.damage.contract_check import validate_damage_response

_MODELS = VersionedPluginRegistry()


def register_model(name: str, version: str, adapter: DamageModel) -> None:
    if (adapter.name, adapter.version) != (name, version):
        raise ContractValidationError("适配器身份与注册名称或版本不一致")
    _MODELS.register(name, version, adapter)


def load_model(manifest_path, device: str = "cpu") -> DamageModel:
    raise NotImplementedError("C2 须注册读取其 ModelManifest 和权重格式的加载器")


def run_damage(request: DamageRequest, options: InferenceOptions | None = None) -> DamageResult:
    validate_contract(request)
    if options is not None:
        validate_contract(options)
    adapter = _MODELS.get(request.model_name, request.model_version)
    result = adapter.predict(request, options)
    validate_damage_response(request, result)
    return result
