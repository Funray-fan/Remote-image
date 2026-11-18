# C3 与 C1 第二阶段对齐（2026-11-18）

上游分支 feature/c1-stage2-model-runtime，固定提交 821d666c3f6614821fb9f211532132a99b9fd7e9。保留此前 C3 展示、R2 空间 QA、R3 背景报告适配，本次未推送 GitHub、未创建 PR、未整分支合并。

## 同步内容

从该提交原样加入 C1 的 core/errors.py、model_manifest.py、model_runtime.py、damage_validation.py、workflows/damage.py，以及原有 10 项集成测试、测试适配器、4 份合成模型包文件和 docs/contract/C1_STAGE2.md。本地 registry.py 已与此版本一致。未修改公共 contracts 或 schema；未覆盖原 C3 六栋建筑样例、R3 背景样例和 R2 代码。

## 页面使用

进入阶段二，数据来源有三项：

- 合成演示：原有六栋建筑静态样例，不调用模型运行时。
- 本地推理结果：读取 C1/C2 交付的 DamageResult、R2 报告、影像/洪水与 R3 背景材料。可选填写 C1 ModelManifest 路径，页面使用 C1 原实现验证文件、权重哈希和参数限制，再核对当前结果的模型身份和类别映射。错误显示 C1 稳定错误码。未提供模型包时只展示结果声明，不声称校验过模型包。
- C1 合成联调：点击「运行 C1→R2→C3 合成联调」，实际注册本地合成加载器、调用 load_model/register_model/run_damage、生成投影 GeoPackage，运行 R2 检查后进入 C3 页面。可切换 C1 允许的切片尺寸和批大小，输出在 outputs/c3_stage2_synthetic/<唯一运行 ID>/，不会覆盖前次运行。

「C1 模型包与推理记录」显示结果参数中的 inference_options、输入资产、模型名称/版本、输入规格、类别、聚合规则、默认值/限制和评估引用。参数按 C1 合并结果展示，不从显示滑块反推模型参数。模型包检查失败时保留独立的结果地图和错误提示，不冒充模型包校验通过。

普通 C1 接入可继续使用 docs/c3/stage2.md 中的公共 DamageResult -> render_damage_layer -> FeatureDetail 调用。公共对象和文件加载仍共用 C3 校验，地图按事件隔离，R2 pass 要求不因 C1 契约检查而取消。warning 只在页面显式人工复核模式查看。

## 合成与真实验收边界

本地 workflows/c3_stage2_demo.py 不是 C2 模型：它复制 C3 已知合成标签，并使用上游 model_weight.placeholder。输入影像的像元规格为联调声明，未做真实配准验收。建筑底图由合成预测几何复制，所以 R2 pass 只证明工程链路运行，不能验证独立定位精度或模型损毁分类准确率。每个结果含 fixture_only 标记和明确警告；run_summary.json 记录这些限制。

合成调用链中保存的是 C1 返回的最终 DamageResult 及有效参数。R2 的疑点报告真实由 R2 代码生成，但依旧基于合成数据。R3 面板复用原合成消费端样例，不声称执行了真实事件 R3 复核。

C1 最新交付没有真实 C2 加载器/权重，也没有完成真实事件的通用阶段二业务编排。当前不会提供一个表面可用却不能执行真实推理的按钮。C2 交付后需在启动处注册其 loader，再用同事件 R1 输入、独立建筑轮廓与 R2/R3 材料完成真实联调。模型包哈希校验只能证明文件与 manifest 一致，不能证明某个结果由此权重生成，也不能代表效果达标。

## 验证命令

```powershell
$env:PYTHONPATH="$PWD/src;$PWD"
.venv/c3-aligned/Scripts/python.exe -X utf8 -m pytest tests --ignore=tests/fixtures -q --basetemp=work/pytest-c1-c3-final
.venv/c3-aligned/Scripts/python.exe -X utf8 scripts/generate_contract_schemas.py --check
.venv/c3-aligned/Scripts/python.exe -m pip check
./scripts/start-local.ps1 -Restart -NoBrowser -Port 8504
```

新增 C3 测试实际运行 C1 -> R2 -> C3 公共接口及 Streamlit 页面，验证有效参数、六栋建筑、未知置信度、模型包关联/哈希错误，以及改变展示阈值不改写原始结果。上游自带的简化 SQLite GeoPackage 样例只用于属性契约测试；本地 C3 联调生成的是 GIS 可读的真实格式 GeoPackage，不用该简化文件作为地图输入。

本次结果：168 项测试、64 个子测试通过，70 份 schema × 2 同步检查通过，pip check 无依赖冲突，git diff --check 通过。20 条警告来自既有洪水算法的 NumPy 运算符待弃用提示。完成更新后已重启 8504 服务，健康检查为 ok，启动日志未见异常；页面验证使用 Streamlit AppTest，未声称完成真实浏览器视觉验收。改动保存在本地工作区，既有用户文档和已有 alignment.md 修改未动。
