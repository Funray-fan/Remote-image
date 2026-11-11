# Remote Image

面向洪涝等自然灾害的遥感灾损评估与救援决策辅助系统。本仓库当前提供的是系统骨架：数据接口、模块注册、流程编排和示例模块。各成员可以分别开发模型训练、无人机正射拼接、GIS 融合、路线规划和可视化，再按统一接口接入。

## 最终系统形态

项目第一版将提供一个本地运行的地图 UI：启动 Streamlit 应用后在浏览器中选择事件和数据、运行阶段流程、切换影像/洪水/损毁/核查/路线图层、查询对象并导出结果。系统不依附地理云等外部平台；外部平台仅作为可替换数据来源。算法模块与 UI 分离，后续可在不修改核心接口的情况下封装 Windows 启动器或部署为内网服务。

最终交付包括：可运行 UI、模块化源代码、固定历史案例、标准地理结果、模型清单、JSON Schema、自动测试、运行说明和演示材料。

当前设计见 [v1.6 协作契约](docs/contract/README.md)、[阶段出口清单](docs/contract/STAGE_EXIT_CHECKLIST.md)和[数据条件](docs/contract/DATA_READINESS.md)。v1.6 新增接口已同步到 Python 类型、模块函数骨架和 `schemas/v2`；当前自检通过只表示接口一致，不表示洪水分析、模型训练、摄影测量和 UI 已全部实现。

三阶段依次交付：SAR 洪水与暴露统计地图 → 一个建筑结构灾损模型及逐建筑结果 → 正射影像核查、道路状态更新及核查前后路线比较。优先同事件集成；独立事件验证必须分开 event_id 展示。

## 设计原则

- 核心系统不绑定某一个深度学习模型、拼接软件或影像平台。
- 模块间传递带坐标与元数据的标准产物，而不是依赖某个成员的内部变量。
- 卫星影像负责区域级研判；无人机正射影像负责重点区域精查。
- 模型训练和在线推理分开。训练组交付模型包与推理适配器，主系统只调用推理接口。

## 当前模块

| 模块 | 职责 | 最低输入 | 标准输出 | 建议负责人 |
| --- | --- | --- | --- | --- |
| 数据获取 | 检索、导入灾前灾后卫星或现场影像 | 研究区、时间、传感器条件 | `RasterAsset` | 数据组 |
| 影像预处理 | 投影统一、裁剪、重采样、质量检查 | 原始影像 | 可比较影像 | 遥感预处理组 |
| 无人机正射 | 空三、正射拼接、地理定向、质量记录 | 原始航片和定位信息 | 带坐标正射影像 | 无人机组 |
| 洪水基线 | SAR 预处理后提取新增水体 | 同网格 sigma0_db 前后影像和 FloodOptions | FloodResult、暴露统计 | R1 / R2 |
| 灾损推理 | 建筑定位与结构损毁识别 | 合适的高分光学影像和模型配置 | 逐建筑 DamageResult；不与洪水混用请求 | C2 |
| GIS 融合 | 融合建筑、人口、道路和设施 | 灾损结果与基础图层 | 区域统计与查询图层 | GIS 组 |
| 救援分析 | 可达性计算、重点排序、候选路线 | 道路、受阻信息、救援点 | 路线和优先级 | 路线组 |
| 可视化 | 图层展示、查询、导出 | 标准化结果 | 系统界面或地图服务 | 前端整合组 |

## 快速运行

首次 clone 后先以 editable 模式安装本项目，再运行示例和测试：

```powershell
python -m pip install -e .
python -m remote_image.main  # 运行 v2 契约自检
python -m unittest discover -s tests -v
python scripts/generate_contract_schemas.py --check
```

需要契约校验工具时安装开发依赖：`python -m pip install -e ".[dev]"`；GIS 与 UI 分别使用 `.[gis]`、`.[ui]`，不要求所有成员一次安装全部重型依赖。

## 接入一个新模型

模型组不应直接把 U-Net 训练代码塞进主流程。应实现 `DamageModel` 协议，并在应用启动时注册：

```python
from remote_image.core.contracts import (
    DamageModel, DamageRequest, DamageResult, InferenceOptions,
)

class MyDamageModel(DamageModel):
    name = "my_damage_model"
    version = "0.1.0"

    def predict(
        self,
        request: DamageRequest,
        options: InferenceOptions | None = None,
    ) -> DamageResult:
        # 在此执行推理，返回符合 DamageResult 契约的空间产物和元数据
        ...
```

启动时用 `register_model(name, version, adapter)` 注册已构造的适配器。通用的
`load_model(manifest_path, device)` 目前仍是待实现入口，模型组需提供与其权重格式
匹配的加载器；契约测试不会加载真实权重。

模型交付至少包括：权重或服务地址、`predict` 适配器、输入波段与分辨率要求、类别编码、预处理规则、样例输入输出、评估指标和版本号。主系统不直接依赖训练脚本。

## 无人机影像接入约定

无人机组可使用 OpenDroneMap、WebODM、Metashape、Pix4D 等工具，但向系统交付时必须统一为：带坐标的正射 GeoTIFF、覆盖范围、坐标系、像元分辨率、采集时间、定位方式和质量说明。不要只交付一张没有坐标的拼接 JPG。

原始重叠航片经成熟摄影测量工具生成正射，不要求训练拼接网络。基础验收可以导入已有正射；原片重建单独离线处理，记录实际引擎/版本。语义分割数据集不保证具备可拼接航带、定位或控制点。道路已确认阻断时排除该边，未知状态单独处理；洪水与道路相交不直接等于确认封路。

灾后无人机影像与灾前低分辨率卫星影像不应直接逐像素比较。系统应先按无人机正射影像的地理范围，从灾前高分影像或建筑轮廓中取得相同区域；若没有同尺度灾前影像，则采用灾前建筑底图加灾后无人机对象核查的路线。

## 推荐协作方式

每个模块独立分支开发，先提交可运行的模拟实现，再替换为真实算法。合并前必须提供：一份样例数据、一次可重复运行命令、标准输出文件、模块说明和最基本的测试。接口变更必须先讨论并更新 `core/contracts.py`，避免其他成员被动修改代码。

详细的目录归属、分支命名、禁止上传内容和 Pull Request 验收规则见 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [GitHub 协作说明](docs/GITHUB_COLLABORATION.md)。`main` 只保存可运行版本，成员不得直接向 `main` 推送个人开发内容。契约及批准状态见 [docs/contract](docs/contract/README.md)。

