# C3 第二阶段建筑灾损地图

本阶段将 C1/C2 提供的逐建筑光学灾损结果接入现有地图。页面显示建筑损毁等级、原始置信度、来源、输入资产、模型名称和版本，并按事件限制洪水叠加。算法可使用 U-Net 或其他模型，C3 不加载训练权重、不执行训练、不推算模型精度。

## 启动

标准安装方式，在仓库根目录执行：

```powershell
python -m pip install -e ".[ui,gis]"
python -m streamlit run app/main.py --global.developmentMode false
```

本地对齐版本使用独立虚拟环境，也可直接运行：

```powershell
.venv/c3-aligned/Scripts/python.exe -m streamlit run app/main.py --global.developmentMode false --server.address 127.0.0.1 --server.port 8504 --server.headless true --browser.gatherUsageStats false
```

打开浏览器访问 http://127.0.0.1:8504，侧栏选择「阶段二 · 建筑灾损」。根目录原有启动器也支持在默认环境缺失时使用此环境。

## 已实现功能

- 合成演示和本地推理结果两种入口；阶段一入口继续保留。
- GeoTIFF 灾前/灾后 RGB 显示，GeoJSON 和 GeoPackage 建筑面显示；GeoPackage 转换为 WGS 84。
- 以损毁等级着色，保留五种固定类别；可切换光学、洪水和建筑图层。
- 地图包含点击属性、放大、缩小、复位和平移控件；详情面板另提供建筑 ID 搜索。
- 阈值只筛选显示与查询，建筑总数和原始预测不变；分类数量明确区分全部与显示。
- 读取事件、图层和建筑 ID；同事件允许叠加洪水，不同事件提示分别查看；合成与真实图层分别展示。
- 非演示结果必须存在 R2 空间质检报告且 status 为 pass；缺少逐建筑结果时给出错误。

## 上游交接

C2 交付训练、模型包、推理适配器、独立测试评估和逐建筑结果；C1 校验并序列化 DamageResult；R2 提供空间质检。C3 通过路径读取序列化对象，不依赖模型架构。

建议结果包：

```text
outputs/<event_id>/stage2/
  damage_result.json
  damage_vector.geojson        # 或 damage_vector.gpkg
  tile_index.geojson           # 或 tile_index.gpkg
  metadata.json
  spatial_qa.json
  layer_manifest.json         # 可选，引用已登记光学 GeoTIFF
```

DamageResult 已对齐队长集成分支的 schemas/v2/damage-result.schema.json，并保留旧版 v1 读取兼容；method 必须为 building_damage，artifacts 必须包含 damage_vector、tile_index、metadata。artifact 路径优先以 damage_result.json 所在目录为基准，不存在时兼容仓库相对路径；绝对路径也必须在仓库内。缺少 GeoJSON CRS 时遵从 RFC 7946，使用 WGS 84 经纬度；投影坐标请交付带 CRS 的 GeoPackage。

v2 每栋建筑保留 building_id、damage_class、confidence、reason、event_id、study_area_id、model_name、model_version，身份字段必须与结果一致，building_id 在当前结果内唯一。v2 不包含旧版 source 字段，详情面板从结果 input_asset_ids 展示输入来源。支持 Polygon 和 MultiPolygon。

v2 允许 confidence=null，但必须同时为 un-classified 并给出非空 reason；未知值不转成 0。阈值为 0 时显示未知记录，正阈值时隐藏，原值和原因保留。旧版 v1 仍只接受数值置信度。本次直接消费 C1 已发布规则，没有修改公共 schema。

在「本地推理结果」里输入结果路径、空间质检路径和可选影像/洪水清单。空间质检路径留空时默认使用结果目录下的 spatial_qa.json。v2 报告按 SpatialQAReport 校验，含 schema_version、status、checks、metrics、warnings、artifacts；正式展示状态必须为 pass，检查项不能含 fail。warning 仅在显式开启复核模式后查看，fail 禁止加载损毁结果。旧版 v1 报告如果带 event_id 则必须匹配。C3 校验交接格式并读取状态和告警，不代替 R2 的空间检查。

光学清单直接支持 v2 LayerManifest 的 layer_id、event_id、kind、path、crs、asset_ids、title、style、min_zoom、max_zoom，也兼容阶段一的 id 配置。v2 清单不添加 synthetic/summary 等额外字段；沿用集成版同目录 summary.json 约定读取合成标记和统计，并核对事件。当前渲染器读取 style.visible、style.color、style.palette，缩放级别范围暂不参与显示过滤。清单内相对路径以清单目录为基准。图层由清单指定；一阶段案例选择器沿用队长对完成运行结果目录的登记方式。

同事件的洪水清单可与光学影像叠加；默认隐藏洪水清单里的灰度影像，让 RGB 底图保持可见，洪水范围/掩膜仍可切换。不同事件仅给出提示，不将另一案例移到当前地理范围。

## C3 接口

2026-11-18 新增 C1 模型包与运行时对接、页面合成调用链和有效推理记录，见 [C1 第二阶段对齐说明](c1-stage2-alignment.md)。真实模型交付与验收边界以该说明为准。

模块：src/remote_image/modules/visualization/stage2.py

```python
result = load_damage_result(result_path, allowed_root=repository_root)
handle = DamageMapHandle(result.event_id)
layer_id = render_damage_layer(result.event_id, result, handle, 0.6)
detail = show_building_detail(result.event_id, layer_id, building_id, handle)
markup = render_map(
    handle.layers,
    vector_features={layer_id: handle.buildings.values()},
    interactive=True,
)
```

DamageMapResult 和 DamageMapHandle 是 C3 内部视图对象，未替换公共 DamageResult / MapHandle 契约。查询函数通过显式 handle 保存当前会话。

2026-11-16 起，公共 interfaces.py 的两个阶段二入口已实现。C1 可传公共 DamageResult，返回 LayerId 和 FeatureDetail；文件与公共对象共用同一校验边界，真实结果仍须 R2 SpatialQAReport，不能用 R3 报告替代。

```python
from remote_image.modules.visualization.public_stage2 import create_damage_map_handle
from remote_image.modules.visualization import interfaces

# result 为 C1/C2 的公共 DamageResult；相对产物路径以 base_dir 为基准。
handle = create_damage_map_handle(
    result.meta.event_id, allowed_root=repository_root, base_dir=result_dir,
    spatial_qa_path=result_dir / "spatial_qa.json",
)
layer_id = interfaces.render_damage_layer(result.meta.event_id, result, handle, 0.6)
detail = interfaces.show_building_detail(result.meta.event_id, layer_id, building_id)
# 交给现有离线渲染器；只读取 handle.state，不改变其建筑索引。
markup = render_map(handle.state.layers,
    vector_features={layer_id: handle.state.buildings.values()}, interactive=True)
```

handle 是公共 MapHandle 的扩展，必须在页面/调用方保留到查询结束。每张地图的 LayerId 唯一；三参数查询通过弱引用查找地图，同一事件的两个页面不会互相覆盖筛选状态。句柄释放后查询会报图层不存在。查询返回属性和几何的独立副本。公共阶段一 render_map 等其他入口仍为团队原有骨架，本次仅落实阶段二两个入口；现有 Streamlit 页面继续使用内部视图适配器。

## R3 背景复核接入（2026-11-16）

对照上游 feature/r3-stage2-context-qa 的 fde02fb3470d5ae3dd38a9fa568cec5fc51d554e 实现消费端，没有合并该分支、复制 R3 算法或修改公共 schema。

在阶段二「本地推理结果」中可提供 R3 的 context_layers.json，以及报告路径（留空默认读取背景清单同目录 context_qa.json）。R3 实际 CLI 可能将报告命名为 r3_context_qa.json，此时显式填写。页面显示检查项、指标、来源、许可、日期、ID 字段和警告；背景图层默认关闭，可单独开启。

- 图层清单、来源清单必须与 DamageResult 的 event_id 和研究区一致，来源路径与实际文件必须对应，所有文件限仓库内。
- ContextQAReport 没有顶层 event_id，因此报告 artifacts.context_layers 必须指向当前清单，event_id 与 sources.event_id 检查必须通过且匹配。旧机器的绝对路径需由上游在当前机器重新生成，不直接套用他人的路径。
- 缺报告时只显示来源，不叠加背景。状态 fail 或任何失败检查均不叠加背景，损毁与光学图层可独立查看；warning 可以查看，同时保留全部警告。
- 未提供研究区相交检查时明确显示覆盖未验证；部分相交不代表完整覆盖，日期已记录不代表灾时一致。人口缺失保持未知，不显示为零。
- 当前报告关联只能核对清单路径和事件检查；公共报告没有输入内容哈希，不能证明文件自复核后未被改动，输入更新后应重跑 R3。

演示新增 context_layers.json 与 context_qa.json，均为人工编写的合成消费端样例，复用原阶段一合成建筑/道路；报告明确标记未检查研究区覆盖，不是 R3 的真实涿州报告或真实空间验收证据。GeoPackage 可重投影展示；GeoJSON 仍要求经纬度，投影坐标背景请交付 GeoPackage。

## 演示验收

tests/fixtures/stage2_synthetic 已迁移为 v2，包含六栋建筑、五种类别、0.62..0.97 的有效演示置信度、一栋未知置信度及原因，以及两张小型 RGB GeoTIFF。全部由规则生成，仅用于工程测试，没有使用 xBD 图片、训练权重或真实灾情预测。

1. 打开阶段二，确认合成提示、建筑总数 6、当前显示 6、模型版本 1.0.0。
2. 阈值调到 0.90，当前显示应为 2，建筑总数保持 6。
3. 搜索 DEMO-004，查看 destroyed / 完全损毁、原始置信度 0.94 和输入资产来源；阈值为 0 时搜索 DEMO-005，确认置信度为未知且有原因。
4. 打开灾前影像，关闭灾后影像，检查 RGB 切换；开关洪水范围。
5. 点击建筑检查属性，操作放大、缩小、复位和平移。
6. 用其他 event_id 的洪水清单测试，确认提示不同事件且不叠加。
7. 使用非演示结果，确认缺失或未通过空间质检时拒绝展示。

自动检查：

```powershell
.venv/c3-aligned/Scripts/python.exe -m pytest tests --ignore=tests/fixtures -q
.venv/c3-aligned/Scripts/python.exe scripts/generate_contract_schemas.py --check
```

测试覆盖阶段一回归、阶段二页面筛选和查询、事件隔离、掩膜不能代替逐建筑结果、空间质检状态、非法属性和越界路径、v2 schema 及旧版兼容、GeoPackage 重投影及 RGB/洪水/建筑叠加。本地对齐的测试数量及结果见 alignment.md。此前浏览器访问审批超时，真实浏览器的点击、平移和缩放仍待人工验收，尚无本次适配的界面截图。

阶段一和阶段二统一通过显式高度的 iframe 显示地图，避免 st.html 默认忽略地图脚本。页面测试检查地图容器实际包含 SVG、影像、要素和交互代码；这仍不能代替真实浏览器的视觉验收。

## 阶段出口限制

本地未提供 xBD、训练权重、真实 DamageResult、独立评估或 R2 质检结果，因此当前完成 C3 展示代码与合成样例联调；真实模型结果的跨岗位联调和视觉验收仍待完成。文档中的 80% 定位和 60% 损毁识别目标属于模型效果要求，不能据本页合成示例声明达标。

地图使用降采样的离线 SVG，适合固定案例。大型区域应由上游提供裁剪、分块或 overview；当前不提供瓦片服务、在线底图及大规模要素的性能保证。建筑几何有效性、空间偏移和切片边缘问题由 R2 质检，C3 不进行算法修正。

## 本次本地验证（2026-11-16）

最终代码运行 `pytest tests --ignore=tests/fixtures -q --basetemp=work/pytest-c3-r3-final-1`：141 项测试、64 个子测试通过。新增 8 项测试覆盖 R3 事件/研究区、来源路径、报告关联、缺报告、失败项拦截，以及公共契约查询、同事件多地图隔离和 R2 报告不可替代；页面 AppTest 验证新增 R3 警告、覆盖提示和背景图层开关。schema 同步检查 70 份 × 2 通过，pip check 无依赖冲突。20 条警告来自既有 flood/baseline.py 的 NumPy 待弃用运算符。本次没有真实浏览器视觉验收或真实模型结果验收。

改动保留在本地工作区，未 push、未建 PR；既有 alignment.md 修改和用户文档未改动。
