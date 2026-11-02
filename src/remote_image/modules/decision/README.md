# R3 基础图层与救援决策

本目录负责基础空间图层、道路网络、候选路线和重点区域排序。当前已经完成阶段一的三个入口：

- `prepare_context_layers`：按研究区裁切建筑、道路、人口等输入，统一到目标 CRS；矢量写为 GeoPackage，栅格写为 GeoTIFF，并生成 `context_sources.json` 与 `context_layers.json`。
- `validate_context_layers`：检查事件/研究区一致性、来源、日期、许可、CRS、覆盖、建筑/道路对象 ID；人口缺失时给出警告，要求后续暴露统计标记为未知。
- `validate_network`：检查道路 ID、投影坐标系、方向/速度/阻断字段、线几何、端点捕捉、连通分量和自环，返回 `NetworkReport`。

## 输入约定

`StudyArea.boundary` 使用可读取的矢量文件路径或 WKT。每个 `SourceRecord` 必须记录来源和许可；建筑及道路必须声明稳定且唯一的 `id_field`。道路网络应使用以米为单位的投影坐标系，因为 `snap_tolerance_m` 不能在经纬度坐标中解释。

阶段一至少需要建筑与道路图层。人口图层允许暂缺，但 R2 的人口暴露值必须标记为未知，不能按 0 处理。洪水与道路相交也不能直接写成已确认阻断。

## 依赖与运行

先安装项目及 GIS 可选依赖：

```powershell
python -m pip install -e ".[gis]"
```

固定样例测试：

```powershell
python -m unittest discover -s tests/unit/r3 -v
```

函数只处理本地已登记数据，不下载在线数据，也不会为缺失输入生成占位图层。阶段三的 `build_road_graph`、道路状态更新、路线和重点区算法仍保留为明确占位，不能把阶段一网络检查报告当成阶段三决策结果。
