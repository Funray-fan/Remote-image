# R1 阶段一交付

本分支交付天津海河洪水与涿州洪水的 R1 数据登记、栅格验证和灾前/灾后影像对齐结果。

本次按用户明确要求，将 GeoJSON 与处理后栅格一并放入功能分支供审核；目标仓库的默认规则仍是不要把运行数据合并进 `main`。是否合并这些数据应由仓库维护者在 PR 审查时确认。

## 文件位置

- 实现：`src/remote_image/modules/data/r1_preprocessing.py`
- 运行入口：`scripts/run_r1.py`
- OSM 转换：`scripts/osm_to_geojson.py`
- GeoJSON：`data/external/osm/geojson/{tianjin,zhuozhou}/`
- 栅格和报告：`outputs/<event_id>/stage1/`
- 数据清单：`data/manifests/r1_stage1_delivery.json`

每个事件包括灾前/灾后 VV GeoTIFF、有效像元掩膜、资产目录、栅格资产元数据、质量报告、预处理参数和运行摘要。输出网格为 EPSG:32650、10 m；天津为 9552 × 7799，涿州为 3920 × 4484。两处 `r1_summary.json` 状态均为 `pass`。

## 许可与限制

Sentinel 数据按 Copernicus Sentinel 数据政策提供。OSM 衍生数据按 ODbL 发布，署名 OpenStreetMap contributors。逐文件 SHA-256、字节数和用途限制记录于数据清单。

AOI 是用于检索的近似框，不等价于官方受灾边界。道路数据是 OSM 底图，不代表道路通行状态；未取得可核实的阻断证据前，不得标记为已阻断。这里的 VV 栅格不是洪水分类结果，也不是建筑损毁标签。人口数据与训练样本未包含在本次提交中。

## 复现与校验

```powershell
python -m pip install -r requirements-r1.txt
python scripts/run_r1.py --event tianjin_2023_flood --prepare-pair --polarization vv
python scripts/run_r1.py --event zhuozhou_2023_flood --prepare-pair --polarization vv
python -m unittest discover -s tests/unit/r1 -v
python scripts/build_r1_delivery_manifest.py
```

清单可通过 `python scripts/build_r1_delivery_manifest.py` 重建；推送前应确认生成结果与提交清单一致。
