"""C2 数据集、训练、评估、打包和推理接口。"""

from pathlib import Path

from remote_image.core.contracts import (
    ApplicabilityReport, ClassMap, DamageRequest, DamageResult, DatasetBundle,
    DatasetManifest, DatasetSplit, EvaluationReport, InferenceOptions,
    ModelArtifact, ModelInputSpec, ModelManifest, RasterAsset, TrainingConfig,
)


def build_dataset(manifest: DatasetManifest) -> DatasetBundle:
    raise NotImplementedError("C2: 按场景或影像对分组，防止切片泄漏")


def train_model(dataset: DatasetBundle, config: TrainingConfig) -> ModelArtifact:
    raise NotImplementedError("C2: 训练一个建筑结构灾损主模型")


def evaluate_model(artifact: ModelArtifact, split: DatasetSplit) -> EvaluationReport:
    raise NotImplementedError("C2: 在独立测试集报告每类指标和限制")


def package_model(artifact: ModelArtifact, spec: ModelInputSpec, class_map: ClassMap, evaluation: EvaluationReport, output_dir: Path) -> ModelManifest:
    raise NotImplementedError("C2: 打包不可变模型版本、输入规格和评估引用")


def predict(request: DamageRequest, options: InferenceOptions) -> DamageResult:
    raise NotImplementedError("C2: 输出逐建筑 damage_vector、tile_index 和元数据")


def check_applicability(asset: RasterAsset, manifest: ModelManifest) -> ApplicabilityReport:
    raise NotImplementedError("C2: 检查无人机影像是否满足该模型输入条件")


def predict_uav(request: DamageRequest, options: InferenceOptions) -> DamageResult:
    raise NotImplementedError("C2: 仅在适用性通过后执行可选无人机模型辅助")
