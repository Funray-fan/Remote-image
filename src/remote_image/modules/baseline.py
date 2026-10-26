"""可导入的业务占位器；不生成不存在的灾情产物。"""

from dataclasses import dataclass

from remote_image.core.contracts import (
    DamageRequest, DamageResult, DecisionRequest, DecisionResult,
    InferenceOptions, OrthomosaicRequest, RasterAsset,
)


@dataclass
class PlaceholderOrthomosaicProcessor:
    name: str = "placeholder_orthomosaic"
    version: str = "0.2.0"

    def build(self, request: OrthomosaicRequest) -> RasterAsset:
        raise NotImplementedError("R3 尚未接入摄影测量引擎；已有正射请走资产登记接口")


@dataclass
class PlaceholderDamageModel:
    name: str = "placeholder_damage_model"
    version: str = "0.2.0"

    def predict(self, request: DamageRequest, options: InferenceOptions | None = None) -> DamageResult:
        raise NotImplementedError("C2 尚未接入训练后的模型；契约测试不要求真实权重")


@dataclass
class PlaceholderDecisionEngine:
    name: str = "placeholder_decision_engine"
    version: str = "0.2.0"

    def analyze(self, request: DecisionRequest) -> DecisionResult:
        raise NotImplementedError("R3 尚未实现路网、候选路线和重点区算法")
