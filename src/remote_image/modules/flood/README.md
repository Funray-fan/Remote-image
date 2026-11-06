# R2 第一阶段

四个公开函数已有实际实现：阈值比较、洪水候选分类、栅格转面、暴露统计。入口保留在 interfaces.py。

运行说明见 [RUNBOOK](../../../../docs/r2/RUNBOOK.md)，方法与限制见 [DESIGN](../../../../docs/r2/DESIGN.md)，学习顺序见 [CODE_READING](../../../../docs/r2/CODE_READING.md)。

现有涿州输入使用 gamma0 线性功率，显式转换为 gamma0 dB。它没有变成 sigma0；共享 SAR 契约的正式接入需要团队审阅。第一版只支持单 VV、两期同阈值、四邻域；不输出未经参考验证的准确率。

第二、三阶段的人工核查与建筑灾损空间 QA 接口仍是待实现任务。
