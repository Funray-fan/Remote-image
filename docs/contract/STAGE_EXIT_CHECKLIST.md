# 阶段出口清单

本文把工作流说明中的接口产物汇总成三个可交接的阶段结果包。目录和文件名是项目组建议统一采用的交付约定；`schemas/v2/` 中的字段、枚举和 artifact 键是 v1.6 新任务的机器接口来源。若实现采用不同物理格式，必须在模块 schema、README 和结果清单中说明，不得静默改 artifact 键。

按 v1.6 修订：以下为目标出口。SAR 参数、模型版本、道路核查和决策比较对象已同步到机器契约 2.0；各岗位仍需完成业务实现与真实数据验收。v2 合成契约测试只验证接口，不自动满足本文全部验收。各阶段共用同一系统，事件数据不足时可以独立案例验证，必须使用不同 event_id 并明确展示。

## 通用交付规则

- 每次运行的结果放在 `outputs/<event_id>/stage1/`、`stage2/` 或 `stage3/`；`outputs/` 不提交 Git。
- 代码、schema、测试、合成 fixture 和小型示例进 Git。真实卫星/无人机影像、GeoPackage 大文件、训练数据、模型权重和运行输出不进 Git。
- 大型或外部文件存于团队批准的共享位置；提交清单记录相对路径/URI、来源与许可、文件大小、SHA-256、采集时间、CRS 和限制说明。
- 各阶段结果都要有可视化交付：可运行地图或明确的截图/演示记录。截图只能辅助验收，不能替代源结果和复跑步骤。
- 每个阶段的负责人保存命令、配置、软件环境、测试日志和局限说明。当前可用的基础检查为 `python -m unittest discover -s tests -v`；各阶段业务 CLI 尚未实现前，不能把拟定命令记录成已通过命令。
- 工程验收与效果验收分开。Schema、artifact 键、类别枚举、CRS/几何、必需文件和固定样例可先冻结；精度目标待 baseline 后由 owner 提议、项目组确认并记入验收记录。

## 阶段一 洪水基线

目录：`outputs/<event_id>/stage1/`

| 成果 | 建议文件名/位置 | 主责 | 交接检查 |
|---|---|---|---|
| 输入资产登记与可复现配置 | `assets.json`、`config.json`、`case_data_readiness.json` | R1 / C1 | asset_id、来源/许可、日期、CRS、输入清单可追溯；进入各阶段前，该阶段最低输入须通过检查并达到 usable |
| 配准和预处理影像 | `prepared/pre_event.tif`、`prepared/post_event.tif`、`sar_processing_report.json`、`threshold_report.json` | R1 / R2 | 按产品状态完成必要定标/校正，统一 sigma0_db；网格及局部配准可核查；记录前/后两组极化阈值和组合规则；无真值时 IoU/F1 为 null |
| 洪水结果 | `flood_mask.tif`、`flood_polygons.gpkg`、`metadata.json` | R2 | 映射到 `FloodResult.artifacts` 的 `flood_mask`、`flood_polygons`、`metadata`；栅格值域与矢量几何通过检查 |
| 上下文图层和暴露统计 | `context/`、`exposure.csv` 或 `exposure.json` | R3 / R2 | 每层有 CRS、来源与日期；统计口径、单位和缺失数据说明齐全 |
| 地图配置和运行摘要 | `layer_manifest.json`、`summary.json`、`run.log` | C1 / C3 | 图层可加载、摘要关联输入和方法版本；C3 可查看灾前/灾后、洪水、建筑/道路及统计 |
| 自动与人工验收 | `validation/`、地图截图或演示记录 | R2 / C1 / C3 | 自动测试通过；固定命令复跑成功；保存实测 baseline，不虚构精度目标 |

阶段出口：完成一条从已登记影像到洪水图层和暴露统计的可复跑流程，并能在地图中检查结果。

## 阶段二 建筑灾损模型

目录：`outputs/<event_id>/stage2/`；权重放于 `models/<model_name>/<version>/` 或团队批准的共享模型存储。

| 成果 | 建议文件名/位置 | 主责 | 交接检查 |
|---|---|---|---|
| 数据/模型规格和模型清单 | `model_manifest.json`、`dataset_manifest.json` | C2 / R1 | 记录模型与数据版本、权重位置及 SHA-256、许可、默认推理参数和限制；权重不进 Git |
| 推理结果 | 必需 `damage_result.json`、`damage_vector.gpkg`、`tile_index.gpkg`、`metadata.json`；掩膜可选 | C2 | 阶段二必须逐建筑提供 building_id、damage_class、confidence、event_id 和模型版本；聚合规则在 manifest 声明。通用协议允许 mask 不代表单纯 mask 能通过本阶段灾损验收 |
| 评估与空间 QA | `evaluation.json`、`spatial_qa.json`、独立测试样例 | C2 / R2 | 按原始场景/影像对分组并检查重叠，不仅检查文件 ID；样本/类别分布、指标、混淆矩阵和空间问题可复核 |
| 地图与运行摘要 | `summary.json`、地图截图或演示记录 | C1 / C3 | 仅同事件且空间范围匹配时叠加洪水和建筑损毁；独立案例分别切换展示，不合并统计；可查看类别、置信度、模型版本和数量；固定样例能复跑 |
| 自动与人工验收 | 测试日志、误差和局限说明 | C1 / C2 / R2 | schema/契约测试通过；效果阈值由 C2 给出 baseline 后评审确认 |

阶段出口：在不改动 GIS/前端调用接口的前提下替换模型实现，并完成独立评估和地图展示。

## 阶段三 无人机核查与救援分析

目录：`outputs/<event_id>/stage3/`；大幅正射影像放共享数据存储，仓库只保存 manifest 和小型测试样例。

| 成果 | 建议文件名/位置 | 主责 | 交接检查 |
|---|---|---|---|
| 正射影像和质量记录 | `ortho.tif` 或登记后的替代影像引用、`ortho_quality.json` | R3 / R1 | 来源类型、是否替代、CRS、覆盖率、控制方式和检查点说明齐全；无检查点时明确定位精度未知 |
| 人工核查链路 | `review_template.csv`、`review_result.gpkg`、`review_qa.json`、`road_state_updates.gpkg` | R2 | 建筑默认 n=min(180,N)、最多200；道路默认 m=min(30,M)、最多50；N/M 为可核查建筑/道路数，数量为0时输出空结果及原因。可保留未知；模板由人判读后导入，记录人员、时间、证据和有效期，QA后关联建筑/道路ID |
| 路网和网络质量 | `road_graph.gpkg`、`network_report.json` | R3 | 路段 ID、拓扑/捕捉规则、来源日期和阻断状态可追溯 |
| 决策结果 | `before/`、`after/`各含`routes.gpkg`与`priority_areas.gpkg`；`effective_road_states.gpkg`、`decision_comparison.json`、`summary.json` | R3 / C1 | 确认阻断边始终排除；未知单独处置。before/after保持相同端点、网格、模型和成本参数；比较可达目标数、绕行、未知边及阻断穿越数。重点区按固定1km网格计算并说明缺失分项和覆盖率 |
| 综合地图和端到端验收 | 地图截图/演示记录、运行日志和测试报告 | C1 / C3 | `run_stage3` 端到端可复跑；能查询核查状态、路线成本/受阻边/不可达、重点区及其理由 |

阶段出口：在地图中同时查看重点区正射、人工核查状态、路网、救援点、候选路线和优先区域，并能解释系统结果与不确定性。

无有效道路核查时允许前后相同，明确未验证道路更新收益。没有独立检查点时正射绝对定位精度记未知。仅有示例数据可以验证系统流程，不能用来声称真实灾区效果。精度目标由业务 owner 根据 baseline 提议，项目组在后续调优/最终测试之前确认并留下批准记录。

## 结果清单模板

每次阶段交接至少记录以下内容，新流程使用 `PipelineRunResult` 对应的 v2 schema；旧的 `schemas/v1/stage-result-manifest.schema.json` 仅用于历史结果：

```text
event_id:
stage:
schema_version:
created_at:
input_asset_ids:
method / model_name / model_version:
artifacts: {artifact_key: relative_path_or_uri}
files: [{path_or_uri, size_bytes, sha256}]
warnings:
run_command:
environment:
tests:
known_limitations:
producer:
reviewer:
```

真实文件的 `sha256` 应由生成/登记流程计算；示例数据不得伪装成真实灾害推理结果。建议每个模块同时提交一正一反 schema fixture；跨角色返回对象优先补 JSON 示例或字段表。任何新增字段、artifact 键、类别值和指标口径，都先由 schema owner 提交兼容性说明，再更新 schema 和下游测试。
