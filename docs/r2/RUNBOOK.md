# R2 涿州案例：运行与结果说明

R2 第一阶段已经实现，并在真实涿州数据上跑通。程序会检查两期影像，按规则标出可能新增的水面，生成边界，再统计这些范围与建筑、道路的交叠。当前没有训练深度学习模型，也没有独立参考标签可用来确认识别精度。

工程位于 D:/codex/Remote-image-r2。原学习目录 D:/codex/Remote-image-r2-learning 保留，原始数据没有被覆盖。

## 先看现成结果

正式示范目录是 [zhuozhou_v1](../../outputs/zhuozhou_2023_flood/stage1/r2/zhuozhou_v1/)。zhuozhou_demo_v1 是开发时较早的一次运行，学习和交接请以 zhuozhou_v1 为准。

先打开 [局部对照图](../../outputs/zhuozhou_2023_flood/stage1/r2/zhuozhou_v1/previews/development_comparison.png)。上方是灾前和灾后，左下是两期数值变化，右下蓝色是规则选出的新增水体候选。白色表示未被选中，灰色表示无法判断。图像是缩略预览，详细边界保存在 TIFF 和 GPKG 中。

本次固定配置使用两期共用的 -18 dB 阈值，未删除小斑块。它是试运行参数，不是经过真值验证的最优参数。

| 本次计算 | 数值与含义 |
|---|---|
| 有效分析面积 | 1757.336 km²，指影像有效矩形范围，不是涿州行政区面积 |
| 未知面积 | 0.392 km² |
| 新增水体候选面积 | 9.6831 km² |
| 候选面数 | 16,075 个，四邻域连接，保留了小斑块 |
| 涉及建筑来源对象 | 8 个；分母图层有 4,698 个 OSM 建筑来源对象 |
| 道路交叠长度 | 9.4409 km；来自 14,949 个 OSM 道路对象 |
| 人口暴露与识别精度 | 暂不可用，字段为 null |

这些建筑和道路来自仓库里的 OSM 快照，来源观测日期和完整性没有得到历史核实。8 个对象不代表现实中只有 8 栋建筑受灾，交叠道路也不能直接判成断路。规则对城市、植被等场景可能漏检或误检，完整限制见 [方法说明](DESIGN.md)。

## 在当前电脑运行一次

打开 PowerShell，执行：

~~~powershell
Set-Location D:\codex\Remote-image-r2
.\.venv\Scripts\python.exe -X utf8 -m remote_image.modules.flood.cli run --config configs/r2/zhuozhou_2023.resolved.json
~~~

程序会创建新的时间命名目录，不覆盖已有结果。终端显示候选面积、建筑来源对象数、道路交叠长度和 summary.json 路径。

也可以使用正式结果目录中保存的配置复跑：

~~~powershell
.\.venv\Scripts\python.exe -X utf8 -m remote_image.modules.flood.cli run --config outputs/zhuozhou_2023_flood/stage1/r2/zhuozhou_v1/resolved_config.json
~~~

首次派生输入需要进行数值转换；之后会核对缓存。运行时间随电脑和磁盘情况变化，不把本机一次耗时作为性能承诺。

## 结果文件怎么读

| 文件 | 作用 |
|---|---|
| flood_mask.tif | 一格一格的分类：1 候选、0 未检出、255 未知 |
| flood_polygons.gpkg | 候选区域的面边界，EPSG:32650 米制投影 |
| flood_polygons.geojson | 同一结果的经纬度展示副本 |
| exposure.csv | 汇总数值和单位 |
| exposure_buildings.csv、exposure_roads.csv | 每个来源对象的交叠和观测覆盖 |
| exposure_features.gpkg | 带上述属性的建筑、道路图层 |
| metadata.json、resolved_config.json | 本次参数、版本与来源 |
| layer_manifest.json | 给 C1/C3 使用的图层路径、类型与坐标信息 |
| validation/spatial_qa.json | 栅格转面后的位置和面积检查 |
| validation/reproducibility.json | 两个独立 Python 环境的复跑比较 |
| validation/evaluation.json | 精度验证状态；当前为 not_validated |
| run.log、run_status.json | 过程记录与成功／失败状态 |

逐对象统计中的空值不是 0。例如一个建筑完全落在未知区域，程序不能判断是否涉及它；部分观察且没有发现交叠的对象也保持未知。CSV 用空字段表示这些 null，字段解释见 DESIGN.md。

QGIS 已安装时可以叠加 TIFF、GPKG 并点击对象；没有 QGIS 也能先看对照图和 CSV，不需要先安装地图软件才能运行程序。

## 参数比较与修改

原始探索配置是 configs/r2/zhuozhou_2023.json。配置中的 6 个阈值与 2 个面积门槛组成 12 个候选；统计只针对声明的开发区。分类和小斑块清理先在完整网格进行，避免开发区边界把斑块切小。

~~~powershell
.\.venv\Scripts\python.exe -X utf8 -m remote_image.modules.flood.cli check --config configs/r2/zhuozhou_2023.json
.\.venv\Scripts\python.exe -X utf8 -m remote_image.modules.flood.cli evaluate --config configs/r2/zhuozhou_2023.json
~~~

evaluate 写出比较表、对照图和新的 zhuozhou_2023.resolved.json。没有参考标签时，第 0 项只是明确选择的试运行参数；程序不会把候选面积最大或最小当成最准确。

第一次学习修改参数，可以在探索配置里将希望试验的阈值放到 candidate_values_db 的第一项，再执行 evaluate 和 run。不要直接改已冻结配置中的阈值而继续引用旧报告，程序会用 STALE_SELECTION 拒绝这种不一致。

留出区在配置中单独登记，并检查与开发区不重叠。当前没有合格参考标签，未开展留出区精度评估。参数比较中所有 Precision、Recall、F1、IoU 均为 null。

## 在另一套干净环境中安装

代码基于 C1 提交 25e34d94c851874515f9c1a9c1dcf6ebb522094c，R1 数据来自 237cff7c433a6e041418f128d01a99453738a0a8。当前工作分支为 feature/r2-stage1，尚未推送远端。

安装 Python 3.11 后，在工程根目录执行以下命令。若已在虚拟环境内，请先退出，避免用错解释器：

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-r2.lock -e ".[r2,dev]"
.\.venv\Scripts\python.exe -X utf8 scripts/prepare_r2_sample.py
.\.venv\Scripts\python.exe -X utf8 -m remote_image.modules.flood.cli evaluate --config configs/r2/zhuozhou_2023.json
.\.venv\Scripts\python.exe -X utf8 -m remote_image.modules.flood.cli run --config configs/r2/zhuozhou_2023.resolved.json
~~~

prepare_r2_sample.py 优先复用同级学习目录中 hash 一致的 TIFF，否则从本地 Git 已登记的 R1 提交读取；部分克隆可能按需联网获取文件。因此，新电脑需要包含该 R1 提交的 Git checkout，而不只是几个 Python 文件。所有下载和大文件保存在工程 data/ 或 work/ 中。

新机器不要直接使用旧 resolved 配置中指向不存在 work/ 报告的引用，先执行 evaluate 生成该机器上的报告及冻结配置。原始数据、派生缓存和运行输出均不提交 Git，data/manifests/r2_zhuozhou_sources.json 记录实际来源和校验值。

## 已完成的检查

2026-11-02，本地 Python 3.11.17 两个独立虚拟环境完成以下核对：

- 全部 90 项自动测试通过，包括仓库原有检查与新增 R2 检查。
- 70 份契约 schema 的两份副本同步检查通过，共享契约没有修改。
- zhuozhou_v1 与 zhuozhou_v1_repro 的分类逐像元一致，错配为 0。
- 面的几何和面积一致，建筑与道路明细 CSV 一致。
- 掩膜转面再回到原网格，错配为 0；两种面积算法均为 9,683,100 m²。
- 两次运行的图层清单、公共结果对象和实际产物均通过检查。

检查图在运行后仅调整过横坐标刻度密度，未改变分析数据。previews/preview_provenance.json 记录了重新绘图所用代码和输入。

测试命令：

~~~powershell
$env:TEMP = "D:\codex\Remote-image-r2\work\temp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 scripts/generate_contract_schemas.py --check
~~~

CI 配置已加入 R2 依赖与测试。本轮只在本地运行这些检查，没有推送或触发 GitHub Actions。

## 给团队的交接说明

四个公开函数仍在 remote_image.modules.flood.interfaces 中，签名保留。其余阶段的 R2 占位接口没有被假装实现。

实际输入为 gamma0 dB，而团队当前 SARPreparedAsset 写的是 sigma0/db。工程通过明确标注的本地适配运行，没有修改共享 schema 或伪造 sigma0。需要由 C1/R1 审阅这个物理规格；地图和总流程的正式接入也还需要 C1/C3 验证。

学习从 [CODE_READING.md](CODE_READING.md) 开始。先把一次运行和几个结果文件认清，再逐步阅读代码。
