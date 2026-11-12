# C3 第二阶段建筑灾损地图

本阶段将 C1/C2 提供的逐建筑光学灾损结果接入现有地图。页面显示建筑损毁等级、原始置信度、来源、输入资产、模型名称和版本，并按事件限制洪水叠加。算法可使用 U-Net 或其他模型，C3 不加载训练权重、不执行训练、不推算模型精度。

## 启动

标准安装方式，在仓库根目录执行：

```powershell
python -m pip install -e ".[ui,gis]"
python -m streamlit run app/main.py --global.developmentMode false
```

本次在项目内隔离安装了测试依赖，也可直接运行：

```powershell
$env:PYTHONPATH="$PWD/.venv/c3-deps;$PWD/src"
python -m streamlit run app/main.py --global.developmentMode false --server.address 127.0.0.1 --server.port 8503 --server.headless true --browser.gatherUsageStats false
```

打开浏览器访问 http://127.0.0.1:8503，侧栏选择「阶段二 · 建筑灾损」。

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

DamageResult 使用仓库现有 schemas/v1/damage-result.schema.json，method 必须为 building_damage；artifacts 必须包含 damage_vector、tile_index、metadata。artifact 路径以 damage_result.json 所在目录为基准，路径须在仓库内。缺少 GeoJSON CRS 时遵从 RFC 7946，使用 WGS 84 经纬度；投影坐标请交付带 CRS 的 GeoPackage。

每栋建筑保留 building_id、damage_class、confidence、event_id、source、model_name、model_version。前三个身份字段 event_id、model_name、model_version 必须与结果一致；building_id 在当前结果内唯一。支持 Polygon 和 MultiPolygon。

当前已发布 v1 schema 仅接受 0..1 的数值 confidence。v1.6 说明中的 null confidence / reason 须先由 C1 发布 schema 迁移，本改动未私自修改公共字段规则。

在「本地推理结果」里输入结果路径、空间质检路径和可选影像/洪水清单。空间质检路径留空时默认使用结果目录下的 spatial_qa.json。报告状态必须为 pass；如果带 event_id 则必须匹配。完整报告仍由 R2/C1 验证，C3 只读取状态和告警，不代替空间检查或公共 schema 校验。

光学清单支持 v1.6 描述的 layer_id、event_id、kind、path、crs、asset_ids、title、style、min_zoom、max_zoom，也兼容阶段一的 id 配置。当前渲染器读取 style.visible、style.color、style.palette，缩放级别范围暂不参与显示过滤。清单内相对路径以清单目录为基准。请通过 C1 清单指定图层，页面不搜索目录或猜测资产。

同事件的洪水清单可与光学影像叠加；默认隐藏洪水清单里的灰度影像，让 RGB 底图保持可见，洪水范围/掩膜仍可切换。不同事件仅给出提示，不将另一案例移到当前地理范围。

## C3 接口

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

DamageMapResult 和 DamageMapHandle 是 C3 内部视图对象，未替换公共 DamageResult / MapHandle 契约。查询函数通过显式 handle 保存当前会话，避免跨用户的全局建筑索引；C1 如需其三参数目标接口，可在会话中绑定此 handle。

## 演示验收

tests/fixtures/stage2_synthetic 中包含六栋建筑、五种类别、0.48..0.97 的演示置信度和两张小型 RGB GeoTIFF。全部由规则生成，仅用于工程测试，没有使用 xBD 图片、训练权重或真实灾情预测。

1. 打开阶段二，确认合成提示、建筑总数 6、当前显示 6、模型版本 1.0.0。
2. 阈值调到 0.90，当前显示应为 2，建筑总数保持 6。
3. 搜索 DEMO-004，查看 destroyed / 完全损毁、原始置信度 0.94 和 synthetic_fixture 来源。
4. 打开灾前影像，关闭灾后影像，检查 RGB 切换；开关洪水范围。
5. 点击建筑检查属性，操作放大、缩小、复位和平移。
6. 用其他 event_id 的洪水清单测试，确认提示不同事件且不叠加。
7. 使用非演示结果，确认缺失或未通过空间质检时拒绝展示。

自动检查：

```powershell
$env:PYTHONPATH="$PWD/.venv/c3-deps;$PWD/src"
python -m unittest discover -s tests -v
```

本次 27 项自动测试全部通过，覆盖阶段一回归、阶段二页面筛选和查询、事件隔离、掩膜不能代替逐建筑结果、空间质检状态、非法属性和越界路径、发布 schema 兼容性、GeoPackage 重投影及 RGB/洪水/建筑叠加。浏览器访问审批超时，真实浏览器的点击、平移和缩放仍待人工验收，尚无界面截图。

阶段一和阶段二统一通过显式高度的 iframe 显示地图，避免 st.html 默认忽略地图脚本。页面测试检查地图容器实际包含 SVG、影像、要素和交互代码；这仍不能代替真实浏览器的视觉验收。

## 阶段出口限制

本地未提供 xBD、训练权重、真实 DamageResult、独立评估或 R2 质检结果，因此当前完成 C3 展示代码与合成样例联调；真实模型结果的跨岗位联调和视觉验收仍待完成。文档中的 80% 定位和 60% 损毁识别目标属于模型效果要求，不能据本页合成示例声明达标。

地图使用降采样的离线 SVG，适合固定案例。大型区域应由上游提供裁剪、分块或 overview；当前不提供瓦片服务、在线底图及大规模要素的性能保证。建筑几何有效性、空间偏移和切片边缘问题由 R2 质检，C3 不进行算法修正。
