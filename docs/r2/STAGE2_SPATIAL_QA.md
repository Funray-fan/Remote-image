# 第二阶段 R2 空间质检

R2 检查 C2 的逐建筑结果是否能可靠地与建筑底图和切片对应。这个检查不计算模型定位准确率或损毁分类准确率；效果指标由 C2 在独立测试集上评估。

## 输入与调用

`check_damage_geography(result, buildings, tile_index, expected_crs, match_tolerance_m, output_dir)` 接收 `DamageResult`、带 `building_id` 的建筑面、切片索引、以米为单位的投影 CRS、匹配容差和输出目录。`DamageResult.artifacts` 必须指向实际存在的 `damage_vector`、`tile_index`、`metadata`；传入的切片路径必须与结果对象一致。三个空间文件均须带相同 CRS。现支持 GeoJSON 和 GeoPackage；GeoJSON 必须声明真实 CRS，不能依赖读取器的默认经纬度假设。

建筑面应使用稳定且唯一的 `building_id`。C2 应声明预测面来自输入建筑轮廓还是模型定位，并交付实际切片边界。若模型输出尚无地理参考，应先由 R1/C2 建立可验证的地理配准，不能给 PNG 人为指定一个投影后直接通过检查。

示例调用：

```python
from pathlib import Path
from remote_image.core.serialization import from_payload
from remote_image.core.contracts import DamageResult
from remote_image.modules.flood.interfaces import check_damage_geography
import json

result = from_payload(DamageResult, json.loads(Path("outputs/example/stage2/damage_result.json").read_text(encoding="utf-8")))
report = check_damage_geography(
    result, Path("data/example/buildings.gpkg"), result.artifacts["tile_index"],
    "EPSG:32650", 2.0, Path("outputs/example/stage2/validation"),
)
print(report.status, report.metrics)
```

路径在交接 JSON 中应按运行环境解析；以上代码假设路径已经可从当前工作目录直接访问。匹配容差 `2.0` 仅作调用示例，正式数值须由影像分辨率、配准误差和建筑轮廓误差确定。

## 检查结果

输出 `spatial_qa.json`、`suspect_samples.csv` 和 `suspect_buildings.geojson`。报告中的 `pass` 表示本模块所检查的空间条件均通过；`warning` 表示需人工复核；`fail` 表示发现明确交接错误。空损毁结果统一为 `warning`，不会冒充模型效果验收。CSV 给出逐条原因，GeoJSON 供地图查看疑点。

检查包括 CRS、几何有效性、事件/研究区/模型身份、ID 完整性与重复、类别/置信度、同 ID 建筑的位置和范围、切片覆盖与边缘、不同建筑预测面的面积重叠。靠近切片边缘只生成复核提示，不能仅凭此认定切片拼接错误。若 C2 使用模型定位的新 ID，须先提供与建筑底图的匹配映射；否则 `building_not_found` 会按失败报告。

目前仓库里的 C2 空适配器只验证第一阶段接口，没有真实模型推理结果。它输出的空图层可用于负向检查，不能充当第二阶段验收样例。收到 C2 的非空固定样例后，需用同一命令重新运行、人工查看疑点，并由 C1/C3 验证地图加载。
