# GitHub 协作与目录说明

## 仓库是唯一代码基线

GitHub 仓库 `https://github.com/Funray-fan/Remote-image` 用于共享源代码、接口、配置、测试和文档。聊天文件、个人磁盘目录和压缩包不能代替仓库版本。数据与模型采用“清单进 Git、实体文件留在本地或受控存储”的方式。

## 目录

```text
Remote-image/
  app/                         C3 的 Streamlit UI 入口与页面
  configs/                     小型 JSON 或 YAML 运行配置
  schemas/v1/                  各模块 JSON Schema
  src/remote_image/
    core/                      C1 公共对象、注册表、错误码
    modules/data/              R1 资产登记和预处理
    modules/flood/             R2 洪水提取和暴露统计
    modules/uav/               R3 正射适配和质量检查
    modules/decision/          R3 路网、路线和重点区
    modules/damage/            C2 模型和推理适配器
    modules/visualization/     C3 地图图层适配
    workflows/                 C1 阶段编排
  tests/unit/<role>/           各岗位单元测试
  tests/integration/           跨模块测试
  tests/fixtures/<event_id>/   小型测试样例
  docs/                        项目、数据、接口和运行文档
  scripts/                     下载、检查和转换工具
  data/                        本地数据，仅 README 与 manifests 入 Git
  models/                      本地权重，仅 README 与 manifests 入 Git
  outputs/                     运行产物，不入 Git
```

## 开始任务

1. 在 GitHub Issue 或任务表中确认岗位、函数、输入、输出和验收人。
2. 更新本地 `main`，再新建任务分支。
3. 只修改自己负责的目录；需要改公共契约时先提交接口提案。
4. 用 `tests/fixtures/` 中的小样例运行，不把真实大数据复制进仓库。
5. 运行本模块测试和相关集成测试。
6. push 任务分支并创建 Pull Request，不直接修改 `main`。

## 避免覆盖他人工作

- 一个公共文件同一时间只设一个 owner；其他成员通过 PR 建议修改。
- 提交前执行 `git fetch origin`，然后在任务分支合入 `origin/main`。
- 冲突涉及他人算法时不要选择“全部保留我方”或直接删除文件，应联系 owner 一起处理。
- 不使用个人绝对路径；配置中的文件路径必须相对仓库根目录。
- 不在算法模块中临时改公共字段；公共字段只在 `core` 和 `schemas` 定义。

## 数据、模型与结果

- `data/manifests/`：记录数据来源、许可、时间、覆盖、sha256 和本地相对位置。
- `models/manifests/`：记录模型任务、版本、权重 hash、输入规格和类别表。
- `outputs/`：只存本地运行结果，不提交。需要评审时上传小型 fixture、截图或发布包。
- 凭据放入本地 `.env`，仓库只提供 `.env.example`，不得写入真实密钥。

## Pull Request 检查

审查者依次检查：文件位置、接口版本、输入输出、测试、空间参考、样例、许可与敏感信息。合并后删除远程任务分支；未完成内容继续开新分支，不在已合并分支长期开发。
