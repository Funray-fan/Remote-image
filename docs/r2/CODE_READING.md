# 根据 R2 产物阅读代码

先按 [RUNBOOK.md](RUNBOOK.md) 完成一次固定案例运行，再从输出回看代码。每次只追一个问题，先不用理解整个仓库。方法与字段的完整约定见 [DESIGN.md](DESIGN.md)。

## 先认清四类文件

打开本次运行清单，找到实际路径：`prepared/` 中是派生分析输入；`flood_mask.tif` 是 0/1/255 的分类；`flood_polygons.gpkg` 是由候选像元生成的面；`exposure_features.gpkg` 是来源建筑与道路的逐对象统计。检查图帮助观察，JSON 和 CSV 帮助核对计算。

学习时保留已经完成的运行目录。修改参数后使用新目录，以免无法分清哪一张图和哪份统计对应哪个配置。

## 第一步 看一对影像为何能比较

阅读 [input_io.py](../../src/remote_image/modules/flood/input_io.py) 的 `inspect_linear_inputs`、`prepare_analysis_inputs` 和 `check_analysis_inputs`，同时打开 `input_provenance.json` 与输入检查报告。

追踪一个 `pre_event`：原始路径和 SHA-256 从哪里来，采集日期在哪里，实际 TIFF 的 CRS、尺寸和仿射变换如何核对，最后如何成为 `core.RasterAsset`。路径能读到和内容满足要求是两个检查。

再看一个有效位置的值如何从线性功率变成 dB。合成示例中 0.01 变成 −20 dB；零和负线性功率不能取对数。转换后仍为 gamma0，只是尺度为 dB。找到程序写入这两项标签的位置，并确认它如何拒绝对已有 dB 再转换。

这一段读完，应能解释为什么仅有“尺寸相同”不足以证明同位置比较，以及原始影像、R1 mask 和最终分析有效范围如何相互约束。

## 第二步 手算一个像元的类别

阅读 [classification.py](../../src/remote_image/modules/flood/classification.py) 的 `classify_arrays`，只跟踪 `valid`、`pre`、`post` 和阈值四个量。

拿纸写下一个假设阈值，把一个灾前较亮、灾后较暗的合成像元代入；再把灾前也改为低于阈值，看看结果为什么变为 0。最后令 `valid=False`，结果应为 255。这里的 0 表示规则未检出，不代表地面已经证实无洪水。

随后看 `clean_components`。它给四邻域候选编号、计算每个连通域的像元数，只删除面积不足的候选。用 [test_r2_classification.py](../../tests/test_r2_classification.py) 中的对角相接、小斑块和未知区域例子，理解为什么不能每个窗口各删一次小斑块。

## 第三步 看参数怎样变成一次运行

阅读 [thresholds.py](../../src/remote_image/modules/flood/thresholds.py) 的 `evaluate_candidates`，对照 `threshold_candidates.csv` 和 `threshold_report.json`。先找到候选顺序、开发区范围、候选面积和被选配置，再看参考标签是否存在。

无参考时，精度字段应为 null，第 0 项只是约定的试运行参数。不要用“哪个面积更大”代替精度依据。案例的开发区由调用方显式传入；直接调用公共比较函数时，默认范围是整个输入。

再读 [baseline.py](../../src/remote_image/modules/flood/baseline.py) 的 `run_flood_baseline`。它主要负责顺序调用和写记录：输入检查、分类、转面、检查、元数据和结果对象。把其中每次调用对应到一份真实输出，比先逐行理解所有内部函数更容易。

## 第四步 把面与像元对上

在 QGIS 打开 `flood_mask.tif` 与 `flood_polygons.gpkg`，放大一个候选边界。面沿像元边界生成，所以边缘呈网格形状；首版没有为好看而简化边界。

阅读 [vectorization.py](../../src/remote_image/modules/flood/vectorization.py) 的 `polygonize_mask` 和 `verify_vector_mask`，对照 `validation/spatial_qa.json`。前者把类别 1 变成面，后者把面再变回像元，检查位置与面积。选一个面，比较 `pixel_count × 像元面积` 与 `area_m2`。分析用 GPKG 的面积来自投影坐标，展示用 GeoJSON 的经纬度不能直接当米。

## 第五步 手查一个建筑和一段道路

阅读 [exposure.py](../../src/remote_image/modules/flood/exposure.py) 的 `_measure_layer` 与 `summarize_exposure`。在输出的 `buildings` 图层中按 `source_id` 找一个对象，依次看总面积、已观察面积、候选交叠面积和 `candidate_exposed`。

先分清完整、部分、未观察三种状态。部分观察但没发现交叠时，`candidate_exposed` 为 null；它不能像完整观察对象那样写 false。再看 `outside_raster_area_m2` 和 `unknown_within_raster_area_m2`，确认无法观察的部分是在影像外，还是影像内的未知区。

道路图层读法相同，但测量单位是米。找一条穿过两个候选面的道路，检查交集长度如何累加，而不是把道路整条长度都算进去。这个长度不表示封路。

最后看同文件中的 `_source_features`：为什么 ID 带 OSM 类型、完全重复记录如何去重、同 ID 不同几何为何报错、坏几何记录到哪里。[test_r2_exposure.py](../../tests/test_r2_exposure.py) 用小型合成像元和几何覆盖这些情况，适合先读测试预期，再返回实现。

## 用最小改动理解结果

完成上面五步后，只改一项已经明确的参数，在新目录复跑，并记录“改了什么、哪些产物变化、为什么”。例如比较一个不同阈值，或者比较关闭与开启小斑块删除；不要同时改输入、范围、阈值和清理规则，否则很难判断变化来自哪里。

合成测试用于核对程序，真实案例用于展示处理过程。能解释这些计算后，再单独开展有参考资料的精度验证；不需要先把一张候选图说成已确认的灾情，才能开始学习。
