# C3 地图适配

`stage1.py` 负责读取 C3 展示用的图层清单、渲染本地 GeoJSON/GeoTIFF、查询要素，以及透传上游统计摘要。它不实现洪水识别、空间统计或公共数据契约；应用页面位于仓库根目录 `app/`。

阶段一的渲染器输出不依赖在线底图，可在离线演示。GeoTIFF 读取需要项目 `gis` 可选依赖；矢量输入按 RFC 7946 使用 EPSG:4326。正式 `LayerManifest`/`FloodResult` 接口由 C1 发布后，再由本模块适配，不修改公共 schema。
