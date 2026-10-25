# Schema v1

各模块主责提交对应 JSON Schema 和正反 fixture，C1 负责注册、版本和 CI 集成。公共字段变更必须通过 Pull Request 说明上下游影响和迁移方式。

- `stage-result-manifest.schema.json`：三个阶段通用的出口结果清单，记录输入资产、artifact 路径、文件校验值、运行命令、测试和交接人。
