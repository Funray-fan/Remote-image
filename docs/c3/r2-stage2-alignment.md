# C3 对齐 R2 第二阶段（2026-11-16）

上游：feature/r2-stage2-spatial-qa，固定提交 c0accc4f7d84a98e3723955ec8ae8d8794c68840，基于现有 C1 集成提交 d21f2f9。本次从 GitHub 读取固定版本，将 R2 的 damage_geography.py、公共接口实现、6 项原始测试和 STAGE2_SPATIAL_QA.md 同步到本地；未整分支合并，未 push、未创建 PR。既有 C3/R3 修改保留，alignment.md 的已有修改和用户文档未动。

## 使用

1. 由上游按 R2 文档调用 check_damage_geography，使用真实投影 CRS、建筑轮廓、切片和经确认的匹配容差。此函数现在也可在本地调用；C3 不自动决定容差。
2. 打开阶段二「本地推理结果」，填写 DamageResult 和空间质检报告路径。R2 示例把报告写到结果目录下 validation/spatial_qa.json，此时必须显式填写；默认路径仍是结果同目录 spatial_qa.json。
3. 查看「R2 灾损空间质检与疑点」中的检查项、指标、报告/CSV 下载和疑点地图。疑点 GeoJSON 按真实 CRS 转为 WGS84 展示，紫色表示 warning，红色表示 fail；图层属性包含 building_id、code、severity 和原始行号。空疑点集不生成地图。
4. 正式损毁展示只接受 pass；warning 可显式选择「复核模式」查看，页面持续显示尚未通过正式空间验收。fail 或含 fail 检查项的报告始终不能加载损毁图层，但复核面板仍保留。空结果仍是 warning、建筑数为零，不冒充模型已完成推理。

R2 和 R3 面板独立。R3 背景图层复核不能代替 R2 灾损空间质检；R2 pass 也不能当作模型定位/分类准确率达到目标。

## 报告关联边界

上游 SpatialQAReport 当前只记录计数、CRS、容差与疑点产物，没有顶层事件 ID、被检 damage_vector 路径或输入哈希。因此 C3 不能独立证明用户选中的报告属于当前结果，也不能验证文件自 QA 后未变动。页面明确提示由交付方确认对应关系，疑点图层在独立复核地图展示，不自动叠加为正式损毁图层。请用当前结果重新运行 R2；不要仅复制其他事件的 pass 报告。公共契约和 schema 未修改。

该上游版本尚未交付 C2 的真实非空模型结果。当前新增联调测试使用工程合成几何调用真实 R2 代码生成产物，证明软件链路可用，不代表真实模型效果、真实地理配准或浏览器视觉验收。

## 验证

新增 C3 联调覆盖 R2 实际 pass/warning/fail 报告、投影疑点重投影、空结果、失败检查拦截、产物越界路径和 Streamlit 复核模式。复跑：

```powershell
$env:PYTHONPATH="$PWD/src;$PWD"
.venv/c3-aligned/Scripts/python.exe -X utf8 -m pytest tests --ignore=tests/fixtures -q --basetemp=work/pytest-r2-c3-final
.venv/c3-aligned/Scripts/python.exe scripts/generate_contract_schemas.py --check
```

本次最终结果：154 项测试、64 个子测试通过；schema 70 份 × 2 同步通过；pip check 无依赖冲突；git diff --check 通过。20 条警告来自既有洪水算法中的 NumPy 运算符待弃用提示。本地预览 8504 健康检查为 ok；未进行真实浏览器视觉验收。
