## 本次任务

- 岗位：C3
- 阶段：一阶段洪水基线可视化
- 实现函数：`load_layers`、`render_map`、`query_feature`、`render_summary`
- 关联 Issue：暂无

## 输入与输出

- 输入对象或文件：本地 `layer_manifest.json`、GeoJSON/GeoPackage、GeoTIFF、上游 `summary.json`
- 输出对象、artifacts 键和文件：离线 SVG 地图、可查询图层、上游统计摘要
- 影响的上下游：消费 R1/R2/R3 阶段一产物；不改 C1 公共接口或上游统计

## 验证

- [x] 本模块测试通过
- [x] 相关仓库测试通过（JSON Schema 测试需 `.[dev]`，当前环境未安装）
- [x] 提供小型合成空间 fixture；Streamlit 应用测试无异常
- [x] 无个人绝对路径、密钥、大型数据、权重或 outputs
- [x] 未修改公共接口，无 schema 迁移

测试命令：`python -m unittest discover -s tests -v`

## 已知限制

- 当前仅支持矢量输入为 GeoJSON/GeoPackage；GeoTIFF 需安装 `.[gis]`。
- manifest 是 C3 临时显示适配格式；C1 发布正式 LayerManifest 后需增加适配，不会把临时格式当作公共契约。
- 合成数据只用于功能演示，不代表真实洪灾、精度或算法效果。
