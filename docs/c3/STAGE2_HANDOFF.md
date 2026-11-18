# C3 第二阶段分支交付

分支：feature/c3-stage2。交付范围为展示代码、公共接口、C1/R2/R3 对接和合成工程联调，不表示整个第二阶段或模型效果验收完成。

## 已完成

- 光学 RGB、同事件洪水与背景图层、逐建筑损毁类别/置信度、类别计数、建筑 ID 查询和模型版本展示。
- 两个阶段二公共接口 render_damage_layer、show_building_detail；多地图与多事件隔离。
- C1 模型包校验、有效推理参数展示、稳定错误码，以及显式合成 C1→R2→C3 调用链。
- R2 报告、CSV 下载和疑点地图；pass 正式展示，warning 显式人工复核，fail 拦截损毁结果。
- R3 背景复核检查项、来源、许可、日期与覆盖提示；事件/研究区和报告关联检查。

## 依赖与合并说明

基于 C1 阶段一集成 d21f2f9e5e123409130eed7631eb3229e2371e04。为使分支独立可运行，包含以下上游已发布实现及其测试，不另行修改其科学算法：

- C1：feature/c1-stage2-model-runtime，821d666c3f6614821fb9f211532132a99b9fd7e9。
- R2：feature/r2-stage2-spatial-qa，c0accc4f7d84a98e3723955ec8ae8d8794c68840。
- R3：消费 feature/r3-stage2-context-qa 的 fde02fb3470d5ae3dd38a9fa568cec5fc51d554e 报告格式；未包含 R3 复核算法或真实报告。

C1/R2 原实现作为依赖单独提交，C3 页面与适配另行提交。后续队长整合时应与这两个固定上游提交核对，避免把依赖代码当作 C3 的算法交付。公共 contracts 和 schemas 未修改。

## 验证与启动

当前代码已通过 168 项测试、64 个子测试；schema 70 份 × 2 同步和依赖检查通过。20 条待弃用警告来自既有洪水算法。合成输入不代表真实灾情或模型精度；测试中的影像为小型规则生成 fixture，model_weight.placeholder 只是文本占位，未上传真实权重、真实遥感输入或 outputs。

在已安装项目依赖的环境中：

```powershell
$env:PYTHONPATH="$PWD/src;$PWD"
python -X utf8 -m pytest tests --ignore=tests/fixtures -q
python scripts/generate_contract_schemas.py --check
python -m streamlit run app/main.py
```

阶段二选择「C1 合成联调」后点击运行。测试合成分支也可选择原「合成演示」。若使用本地启动脚本，代码更新后应重启服务，避免正在运行的 Python 模块仍是旧版。

## 待完成

- R1 提供当前事件的可用输入、地理参考与质量证据。
- C2 提供真实训练模型包、加载器、非空固定推理样例和独立评估。
- 同事件真实数据下复跑 C1/R2/R3，并由 C3 完成加载、查询和人工视觉验收。
- 真实浏览器的视觉与交互验收及截图尚未完成，本分支没有声称已验收。

R2 当前报告没有事件 ID/输入哈希，仍需交付方确认与当前结果对应；R3 的相交检查不代表完整覆盖。模型包校验也不能替代模型科学效果评价。
