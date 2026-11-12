# R1 数据与预处理

资产登记、栅格检查、裁剪、投影、重采样和模型输入准备放在此目录。

## R1 v1 实现

- `r1_preprocessing.py` 提供资产登记、状态更新、栅格验证和灾前/灾后配对预处理。
- `scripts/run_r1.py` 从 Planetary Computer STAC 获取 Sentinel-1 RTC 元数据并验证远程 COG；添加 `--prepare-pair` 会输出同网格 GeoTIFF。
- 栅格依赖安装：`python -m pip install -r requirements-r1.txt`。
- 测试：`python -m unittest discover -s tests/unit/r1 -v`。

该实现沿用阶段一 v1.5 任务定义中的 R1 数据对象。合并前由 C1 和 R2 对照仓库 `core/contracts.py` 完成公共类型映射与下游验收；不应自行改动公共契约。

## 已处理案例

天津海河洪水与涿州洪水的 GeoJSON 和 R1 `outputs/<event>/stage1/` 结果存放于本分支。文件来源、许可、用途限制和 SHA-256 见 `data/manifests/r1_stage1_delivery.json`。OSM 衍生 GeoJSON 按 ODbL 使用并署名 OpenStreetMap contributors；AOI 是数据检索近似框，阻断道路未被推断或伪造。
