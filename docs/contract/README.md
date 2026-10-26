# 协作契约与修订状态

本目录保存协作契约、评审修订和 fixture 说明。当前阅读版本为 **v1.6**，配套机器契约为 **2.0**。Python 公共对象、模块函数骨架、JSON Schema 和合成 fixture 已同步；业务算法仍按分工实现。

- Word/PDF 阅读版用于分工、评审和归档；
- `schemas/v2/` 是 v1.6 新任务的机器可读字段、枚举和必填规则来源；`schemas/v1/` 仅保留历史兼容；
- `tests/fixtures/contracts_v2/` 是隔离的合成测试数据，不代表真实模型精度；
- 阶段二真实训练结果在模型验收时提交，不用于反向修改已冻结接口。

新开发以 `schemas/v2/`、`core/contracts.py` 和各模块 `interfaces.py` 为准。Schema 由生成脚本维护，CI 检查两份安装/源码副本一致。不得把 v2 结果写入旧版 fixture，也不得把 CI 通过理解为三阶段业务完成。

- [v1.6 Word 源文件](workflow-contract-v1.6.docx)
- [v1.6 修订与迁移清单](REVISION_V1_6.md)
- [三阶段数据条件](DATA_READINESS.md)
- [阶段出口清单和结果清单模板](STAGE_EXIT_CHECKLIST.md)
- [阶段二合成 fixture 说明](STAGE2_FIXTURES.md)

历史版本：

- [v1.5 Word 源文件](workflow-contract-v1.5.docx)
- [v1.5 PDF 阅读版](workflow-contract-v1.5.pdf)
- [v1.4 Word 源文件](workflow-contract-v1.4.docx)
- [v1.4 PDF 阅读版](workflow-contract-v1.4.pdf)
