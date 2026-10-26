"""R1 数据登记和预处理接口。算法实现由 R1 在这些边界内补充。"""

from pathlib import Path

from remote_image.core.contracts import (
    AssetRecord, AssetStatus, GridSpec, PreparedInputs, RasterAsset,
    RasterValidationReport, ResamplingName, SARPreparedAsset,
    SARPreprocessSpec, StudyArea,
)


def register_asset(asset: RasterAsset, record: AssetRecord, catalog: Path) -> AssetRecord:
    raise NotImplementedError("R1: 将资产与来源记录写入 catalog")


def update_asset_status(catalog: Path, asset_id: str, status: AssetStatus, note: str | None = None) -> AssetRecord:
    raise NotImplementedError("R1: 更新资产状态并保留变更说明")


def validate_raster(asset: RasterAsset, area: StudyArea, required_bands: tuple[str, ...] = ()) -> RasterValidationReport:
    raise NotImplementedError("R1: 检查文件、CRS、覆盖范围、波段和时间")


def preprocess_sar(source_path: Path, input_record: AssetRecord, spec: SARPreprocessSpec, output_dir: Path) -> SARPreparedAsset:
    raise NotImplementedError("R1: 按产品状态输出 sigma0_db 和处理报告")


def prepare_pair(pre: RasterAsset, post: RasterAsset, area: StudyArea, target_crs: str, grid: GridSpec, resampling: ResamplingName, output_dir: Path) -> PreparedInputs:
    raise NotImplementedError("R1: 统一前后影像网格并记录有效掩膜")


def prepare_model_inputs(pre: RasterAsset | None, post: RasterAsset, area: StudyArea, spec, output_dir: Path) -> PreparedInputs:
    raise NotImplementedError("R1: 按 C2 提前交付的 ModelInputSpec 准备模型输入")


def clip_to_area(asset: RasterAsset, area: StudyArea, target_crs: str, output_path: Path, resampling: ResamplingName) -> RasterAsset:
    raise NotImplementedError("R1: 裁切并登记新的栅格资产")
