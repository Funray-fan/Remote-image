# 阶段一本地整合、问题修订与验收

验收日期：2026-11-11。整合分支：`feature/c1-stage1-integration`。

## 交付结论

阶段一工程链路已在本机跑通，并提供 Streamlit 网页：案例选择、灾前灾后图层切换、候选水体和建筑/道路叠加、地图要素点击、对象查询、摘要下载、网页按钮重跑真实案例。默认显示最近一次涿州结果；合成功能样例可切换。

工程通过不代表科学精度通过。`pipeline_result.json` 使用公共 v2 契约，状态保持 `partial`：人口输入、独立参考标签和真实建筑损毁模型尚缺，不能给出已验证的识别精度或救援通行结论。

## 来源

基线 main：`1dff827`。整合 C1 契约 `25e34d9`、R2 分支（含 gamma0 扩展）、R3 `703d1a5`、C2 `a15a3f3`、C3 `455e3d2`、C1 编排 `0750add`。R1 代码和清单从 `origin/feature/r1-stage1` 选取；大型数据从固定 R1 提交 `237cff7c433a6e041418f128d01a99453738a0a8` 提取到本地 `data/zhuozhou/`，不纳入整合提交。

## 问题标注与修订

| 编号 | 原问题 | 修改与验证 |
|---|---|---|
| INT-01 | C1 两个分支各自新增 validation.py，直接合并冲突 | 保留 v2 schema/语义检查，同时接入通用文件检查；schema 同步及整套测试验证 |
| INT-02 | C1 编排仍写 v1 元数据、未自动校验步骤返回值；manifest 失败可能继续 pass | 公共元数据使用 2.0；返回对象进入契约、文件、事件/研究区检查；manifest 失败置 fail |
| INT-03 | C2 缺 model_version，元数据及空 GeoJSON 不满足 v2 | 请求核对模型名/版本；元数据和 GeoJSON 写 2.0；修订旧测试，验证完整产物 schema |
| INT-04 | C1 示例 steps 为空，模块分散 | 新增 workflows/integrated.py 与真实案例配置，接通 R1 检查、R2 转换、R3 裁切/QA、R2 分类/矢量/暴露、C2 空基线检查及 C3 清单 |
| INT-05 | R3 裁切后的图层路径与 SourceRecord 路径不同，R2 暴露统计拒收 | 输出来源记录指向实际交接文件；另存 original_context_sources.json 保留原始路径，完整合成交接测试覆盖 |
| INT-06 | C3 只读临时 manifest；R2 metrics 在界面不显示 | 直接验证并读取公共 v2 LayerManifest，映射 layer_id/style；支持 metrics 与 units；null 显示未知 |
| INT-07 | 图层查询标识和地图点击标识不一致 | 共用 source_id/candidate_id 等标识规则；验证真实地图点击和合成道路来源 ID 查询 |
| INT-08 | st.html 不执行地图点击脚本 | 改为 Streamlit HTML 组件；真实浏览器点击后属性面板有内容 |
| INT-09 | 投影栅格仅按经纬度外包框拉伸，分类缩略使用平均值 | 栅格先投影到地图使用的 Web Mercator；类别使用最近邻、连续影像使用平均值；底层统计不变 |
| INT-10 | CI 仅 unittest，遗漏 C2 和新增 pytest 函数测试 | CI 改为 pytest 全量收集并安装 UI 依赖；本机完整收集 121 项测试 |
| INT-11 | PowerShell 5.1 默认编码及系统临时目录导致启动/测试失败 | 启动脚本写 UTF-8 BOM；临时目录使用 work/temp；本地网页已实际启动 |

兼容说明：新的公共对象和 `pipeline_result.json` 为 v2。`file_manifest.json` 继续使用仓库现有 v1 哈希清单格式，作为辅助台账，不能当成 v2 公共运行结果。未修改公共 schema 字段；保留了 R2 的 gamma0/sigma0 扩展。

## 环境与启动

本机解释器来源为 Anaconda Python 3.13.9。项目 `.venv` 使用 `--system-site-packages` 复用现有 GIS/Streamlit，项目以 editable 模式安装；没有对 Anaconda base 执行升级。`requirements-local.lock` 记录本次直接依赖版本，`requirements-r2.lock` 保留岗位原环境记录。

双击项目根目录 `启动网页.cmd`，访问 http://127.0.0.1:8501 。网页仅监听本机，运行日志与 PID 位于 `work/`。

首次配置（其他机器）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup-local.ps1 -Python python
.\.venv\Scripts\python.exe -X utf8 scripts/prepare_r2_sample.py
powershell -ExecutionPolicy Bypass -File scripts/start-local.ps1
```

真实样例依赖固定 R1 Git 提交；克隆必须能读取该对象，数据准备脚本按哈希校验后提取。不要在 Git 中删除历史大数据提交后继续假定此获取方式有效；迁移共享存储时应同步清单与数据准备脚本。

## 验收结果

1. `python -m pytest tests -q`：121 项通过，包含新增跨岗位合成案例与缺输入失败测试。
2. `python scripts/generate_contract_schemas.py --check`：公共 schema 两份副本同步通过。
3. 合成端到端：候选面积 9,600 m²，交叠建筑对象 1，道路交叠 120 m，人口为 null；能够读取 v2 图层清单、渲染栅格/矢量并查询 `way:1`。
4. 真实涿州：候选面积 9,683,100 m²，交叠建筑来源对象 8，道路交叠 9,440.891146 m；与 R2 已交付的数值一致。
5. Chromium 实测：默认候选面 16,075 个；地图要素点击、真实/合成案例切换、统计显示通过；无浏览器脚本错误。网页按钮真实复跑通过，自动切换到新结果；清空案例选择显示提示，不触发异常。

本机原始日志在 `work/release-tests.txt`、`work/browser-acceptance.json`、`work/web-run-acceptance.json`。真实运行产物在 `outputs/zhuozhou_2023_flood/stage1/integrated/<run_id>/`。每次新建运行目录，失败运行保存 failed 状态，不覆盖已完成成果。

截图：[真实案例](acceptance/real.png)、[合成功能样例](acceptance/synthetic.png)、[网页按钮复跑](acceptance/web-run.png)。

## 尚缺的业务条件

- 无合格人口图层：人口暴露保持 null。
- 无独立且时间匹配的参考标签：Precision/Recall/F1/IoU 保持 null。
- OSM 来源观测日期未知：历史一致性未验证，不能称为完整的灾时建筑/道路清单。
- C2 仍是空基线：未运行真实建筑灾损识别，不将空结果解释为无损毁。
- 无道路核查：交叠道路不等于阻断，当前不提供已验证救援路线。
- 本次完成阶段一本地整合；阶段二模型与阶段三核查/决策不在本次工程验收范围。
