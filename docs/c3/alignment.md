# C3 与阶段一集成分支的本地对齐

本次把 feature/c1-stage1-integration 的固定提交 d21f2f9e5e123409130eed7631eb3229e2371e04 合入本地 feature/c3-stage2，保留此前 C3 阶段二和地图容器修复。只在本地保存提交，没有 push 或创建 Pull Request。

## 对齐结果

- 阶段一保留队长的案例选择、涿州分析按钮、图层来源、候选水体/建筑/道路统计、未知人口和摘要下载。
- 阶段一直接加载并校验 v2 LayerManifest，读取同目录 summary.json 的 metrics 和 synthetic 标记；合成联调结果不会标成真实涿州案例。
- 图层默认状态与队长版本一致，flood_mask 自动采用分类色表，同时尊重清单中的显式 style 设置。
- 保留队长的 source_id/candidate_id 等查询规则及 Web Mercator 栅格重投影，分类采用最近邻，连续影像采用平均值。
- 阶段二支持 v2 DamageResult、DamageVector、SpatialQAReport，保留旧版 v1 输入兼容；没有修改公共契约或 schema。
- v2 不再要求旧 source 属性；详情显示输入资产 ID、模型名称和版本。null 置信度必须为 un-classified 且给出 reason，阈值只改变展示。
- 两阶段共用有明确高度的交互地图容器，保留光学 RGB、分级着色、建筑查询和事件隔离。
- 原启动脚本在默认 .venv/Scripts 环境不存在时，可使用本地 .venv/c3-aligned 环境；保留默认启动方式。

公共接口模块 interfaces.py 中由团队保留的 NotImplementedError 骨架仍保留；当前可运行 UI 通过 C3 视图适配器消费序列化公共结果，未声称所有跨岗位调用入口已实现。

## 运行与验证

对齐版网页已在 http://127.0.0.1:8504 启动。复跑：

```powershell
./scripts/start-local.ps1 -NoBrowser -Port 8504
```

使用独立环境，避免旧网页占用旧依赖：

```powershell
New-Item -ItemType Directory -Force work/temp | Out-Null
$env:PYTHONPATH="$PWD/src;$PWD"
.venv/c3-aligned/Scripts/python.exe -m pytest tests --ignore=tests/fixtures -q --basetemp=work/pytest-alignment-verify
.venv/c3-aligned/Scripts/python.exe scripts/generate_contract_schemas.py --check
.venv/c3-aligned/Scripts/python.exe -m remote_image.main
.venv/c3-aligned/Scripts/python.exe -m pip check
```

本次结果：133 项测试通过、61 个子测试通过；70 份 schema 的两处副本同步检查通过；v2 契约自检通过；依赖无冲突。pytest 排除 fixtures 目录的递归收集，测试仍读取所有规定 fixture 文件。

新增 C1→C3 测试实际执行 prepare_demo 和 run_case，读取生成的 v2 清单，再进入 Streamlit 页面，验证：

- 新增水体候选面积 9,600 m²；
- 交叠建筑对象 1、人口暴露为未知；
- 打开道路图层后地图保留 way:1 来源 ID；
- 阶段一、阶段二、阶段一往返切换无异常。

其余测试覆盖 v1 兼容、v2 空置信度及原因、逐建筑属性和路径校验、空间质检状态、投影和分类显示。上游洪水模块有 20 条 NumPy 运算符待弃用提示，不影响当前测试结果；本次未修改该算法。

## 数据与验收边界

本地尚无队长涿州历史案例的完整输入。已尝试按照 data/manifests/r2_zhuozhou_sources.json 下载固定 R1 样例并获取其固定 Git 提交，均遇到 GitHub 网络连接失败，未生成真实案例运行结果。当前默认仍是合成功能样例。

网络可用后，按团队原流程获取固定 R1 提交并运行 scripts/prepare_r2_sample.py，再用网页「运行涿州阶段一分析」按钮生成本地结果。必须校验来源清单和配置中的文件哈希，不能用合成影像替代真实案例并复用其统计数字。

C3 代码及合成链路已完成本次分支对齐；真实涿州复跑、浏览器视觉与交互验收、阶段二真实模型及空间质检结果联调尚待完成。队长此前提交的 docs/acceptance 截图属于上游验收材料，不能算作本次修改的验收截图。
