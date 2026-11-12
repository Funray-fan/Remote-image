# C1 阶段一实现说明（不改变 v1 公共契约）

## 本次新增
- `core/config.py`：JSON/YAML 配置加载、必填项检查、项目相对输出路径解析。
- `core/validation.py`：结果产物/元数据检查，以及调用现有 JSON Schema 的通用校验器。
- `workflows/stage1.py`：按配置顺序导入并调用 R1/R2/R3 函数，记录步骤状态、耗时、错误并输出 `outputs/<event_id>/stage1/summary.json`。
- `tests/integration/test_c1_stage1.py`：C1 集成入口测试。

## 契约兼容性
本次不修改 `core/contracts.py` 中任何 dataclass，不修改现有 `schemas/v1/*.schema.json`，不更改现有工作流 `AssessmentWorkflow` 的签名。结果校验器直接接受现有 dataclass 或 dict。新增的 summary 是 C1 运行日志，不作为 R2 `FloodResult` 的替代品。

## 调用约定
每个 step 的 callable 形如 `remote_image.modules.<owner>.<module>:<function>`，kwargs 与模块 owner 已确认的函数签名一致。`$step.<name>` 可引用前序步骤返回值。R1/R2/R3 函数尚未出现在当前仓库时，配置不能填写虚构函数；对应模块 PR 合并后再联调。

## 已知限制
当前仓库中的 `modules/data`、`modules/flood`、`modules/decision` 只有 README/包入口，没有阶段一业务函数实现。因此 C1 可验证配置、调度、失败处理、日志和契约校验，但不能独立产出真实洪水掩膜、洪水面或暴露统计。空步骤运行会返回 warning，不会伪报成功。

## CI
仓库当前 CI 使用 Python 3.11 与 `python -m unittest discover -s tests -v`。本次测试遵循 unittest，不改变 CI 配置。
