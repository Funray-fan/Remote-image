# R3 第二阶段：基础图层复核交付

日期：2026-11-14。开发分支：`feature/r3-stage2-context-qa`；基于阶段一整合分支 `feature/c1-stage1-integration`。本交付落实 v1.6 分工中的 `validate_context_layers(layers: ContextLayers, event_id: str) -> ContextQAReport`，不包含 C2 的 xBD 训练、R2 的灾损空间 QA 或第三阶段路线计算。

## 实现与接口

- `src/remote_image/modules/decision/stage2.py`：检查当前事件与来源事件一致、建筑/道路必需图层、来源及许可、观测日期、文件可读性、CRS、几何类型、非空范围和对象 ID 唯一性。返回公共 v2 `ContextQAReport`，不新增或修改 schema。
- 可选传入 `area=StudyArea(...)` 后检查研究区 ID 和图层是否与当前事件边界相交。不传边界时返回 `event_coverage=warning`，只记录图层自身 bounds，不能把同一 event_id 当作已验证地理覆盖。
- `src/remote_image/modules/decision/interfaces.py` 对外提供阶段二签名；原有阶段一 `(layers, StudyArea)` 调用仍保留。
- 命令行读取阶段一 `context_layers.json` 并写入 `context_qa.json`。若有失败项，进程退出码为 1；仅警告时退出码为 0，报告状态仍为 `warning`。

## 本机涿州案例复核

输入为阶段一整合结果目录下的 `context/context_layers.json` 和 `study_area.gpkg`。复核运行命令（先将 `<run_id>` 替换为本机实际运行目录）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m remote_image.modules.decision.stage2 `
  --context outputs/zhuozhou_2023_flood/stage1/integrated/<run_id>/context/context_layers.json `
  --event-id zhuozhou_2023_flood `
  --area-boundary outputs/zhuozhou_2023_flood/stage1/integrated/<run_id>/study_area.gpkg `
  --area-id zhuozhou_2023_flood --area-crs EPSG:32650 `
  --output outputs/zhuozhou_2023_flood/stage2/r3_context_qa.json
```

本机使用 `20261111T014446_400324Z` 阶段一结果复核：状态为 **warning，无失败项**。建筑 4,698 个、道路 14,949 个，二者 CRS、几何、ID 唯一性和研究区相交检查通过。警告为：缺人口图层；建筑与道路来源观测日期均未知。历史 OSM 快照并未核实为灾时完整资产清单，不能因这些结构检查通过就推断建筑灾损、道路阻断或时相一致。

运行报告位于本机 `outputs/zhuozhou_2023_flood/stage2/r3_context_qa.json`，按仓库规则不提交 Git；本说明与小型合成测试提交 Git。

## 与 xBD / 第二阶段模型的交接条件

xBD 模型训练可使用灾前/灾后 PNG，但这些样本与涿州 SAR 案例没有自动对应关系。若 C2 用 xBD 独立事件推理，R1/R3 必须为该事件登记匹配的建筑、道路和研究区边界，再用相同的 `event_id` 复核。跨事件图层会得到 `fail`；无地理参考的 PNG 无法凭此报告取得地图定位。

R3 将 `ContextQAReport` 交给 C1 编排和 R2 空间质检。R2 仍负责 `check_damage_geography`，C2 仍负责逐建筑 `damage_vector`、模型版本和独立评估。R3 报告通过也不能代替灾损结果或科学精度验收。

## 验证

- `python -m pytest tests -q -p no:cacheprovider`：126 项通过，含新增 5 项阶段二 R3 测试（同事件/覆盖、缺边界、跨事件、不相交、日期未知和重复 ID、阶段一接口兼容）。
- `python scripts/generate_contract_schemas.py --check`：70 份 schema 的两份副本同步。
- 上述真实涿州 CLI 运行成功，结果状态 `warning` 且无失败项。

可继续补充当前 xBD 事件的来源、许可、观测日期和覆盖证据后重跑；在输入未取得前，不把涿州复核结果当作 xBD 事件验收。
