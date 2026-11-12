"""R3 无人机正射接口；摄影测量使用成熟工具，不在此训练拼接模型。"""

from pathlib import Path

from remote_image.core.contracts import OrthomosaicQualityReport, OrthomosaicRequest, RasterAsset


def build_orthomosaic(request: OrthomosaicRequest) -> RasterAsset:
    raise NotImplementedError("R3: 调用已选定的摄影测量引擎生成正射 GeoTIFF")


def check_orthomosaic(asset: RasterAsset, check_points: Path | None, target_crs: str, min_coverage: float) -> OrthomosaicQualityReport:
    raise NotImplementedError("R3: 检查覆盖、空洞、叠合和可验证的定位精度")
