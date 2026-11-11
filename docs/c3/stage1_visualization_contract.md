# C3 第一阶段可视化输入需求

这份文档是 C3 的联调清单，不替代 C1 的公共 schema。C1 发布正式接口后，应逐项映射并记录兼容关系。文件归属遵循仓库 `CONTRIBUTING.md`：实现位于 `app/`、`src/remote_image/modules/visualization/`，测试位于 `tests/unit/c3/`。

## 必需输入

- `event_id`
- `layer_manifest.json`
- 灾前和灾后影像路径、时间、CRS、来源
- `flood_mask.tif`
- `flood_polygons.gpkg` 或 GeoJSON
- 建筑和道路上下文图层
- `summary.json` 或 `exposure.json`

合成 fixture 还应使用 `synthetic: true`，并明确注明不能代表真实灾情结论。

## 页面行为

- 图层开关：灾前、灾后、洪水掩膜、洪水范围、建筑、道路
- 图例：明确颜色、类别、NoData
- 查询：返回 `feature_id`、面积、事件 ID、来源、时间和方法版本
- 摘要：洪水面积、受影响建筑数、人口统计和 warnings
- 错误：缺文件、JSON 字段缺失、CRS 不一致时显示可操作错误
- 离线：演示不依赖在线底图或远程 API

## 待 C1 确认

1. `LayerManifest` 的正式字段名和版本。
2. `FloodResult.artifacts` 的路径约定。
3. `summary.json` 的统计字段和单位。
4. GeoTIFF/矢量的 CRS 与时间字段。
5. UI 启动命令和集成测试入口。

## 演示顺序

1. 启动 Streamlit 页面并选择事件 manifest。
2. 依次打开灾前影像、灾后影像、洪水掩膜、洪水范围、建筑和道路图层。
3. 点击洪水范围中的要素，核对 feature_id 和来源属性。
4. 查看上游 summary 中的洪水面积、受影响建筑数、人口和 warning。
5. 展示数据来源、时间、CRS、方法版本和适用限制。
