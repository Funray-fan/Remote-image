# 三阶段数据条件

已有xBD训练影像来源，项目重点转到输入规格、独立评估和系统接入。用户提供的xBD入口：[HyperAI](https://hyper.ai/cn/datasets/13272)。本轮不执行下载，不把目录可见等同于目标案例数据已取得。

| 阶段 | 必要数据 | 不满足时 |
|---|---|---|
| 一 | 同事件灾前/灾后Sentinel-1，可比轨道/极化与产品级别，基础建筑/道路 | 换历史洪水案例；人口可缺，统计标未知 |
| 二 | 符合ModelInputSpec的高分光学时相与标签、场景分组测试集、算力 | 用xBD独立事件训练评估，与阶段一分event_id展示；低分影像放大不能补细节 |
| 三 | 覆盖重点区的正射、建筑/道路ID、路网、救援点和人工核查证据 | 已有公开/合作正射可接入；仅示例则验流程，不能宣称真实效果 |

每事件记录：event_id、stage、purpose、source_url、license_id、采集日期、产品/波段/像元大小、标签、存储与算力、owner、checker、checked_at、evidence_uri、status、limitations。

状态：planned拟用；verified已查目录/许可；acquired取得并校验；usable经空间、辐射或模型适用性检查。保留证据后升级状态。

无人机原始照片经过重叠匹配、空三、重建与正射纠正生成GeoTIFF，无需训练拼接网络。公开分割图片不保证是完整可拼接航带。候选参考：

- [ODM样例](https://github.com/OpenDroneMap/odm_data)：测试摄影测量，逐子集检查重叠、定位、控制点与许可。
- [FloodNet](https://github.com/BinaLab/FloodNet-Supervised_v1.0)、[RescueNet](https://github.com/BinaLab/RescueNet)：无人机灾害场景理解参考，不默认有灾前配对/正射定位/可拼接原片。

无独立检查点时绝对定位RMSE未知；有CRS不代表对准。PNG训练样本不能硬填CRS后冒充定位影像。没有同尺度灾前影像时按对象核查，不直接跨尺度逐像元相减。
