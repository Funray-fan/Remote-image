# Remote Image 协作规则

本仓库通过分支和 Pull Request 协作。`main` 只保存能够运行和通过测试的集成版本，任何成员不得直接把个人完整项目复制到仓库根目录。

## 标准流程

```powershell
git switch main
git pull origin main
git switch -c feature/r1-short-task

# 修改并测试后，只添加本任务文件
git add src/remote_image/modules/data tests/unit/r1
git commit -m "feat(r1): add raster validation"
git push -u origin feature/r1-short-task
```

随后在 GitHub 创建 Pull Request。至少由直接下游岗位和 C1 各检查一次后才能合并。

## 分支与提交

- 功能分支：`feature/<岗位>-<任务>`，如 `feature/r2-flood-polygon`。
- 修复分支：`fix/<岗位>-<问题>`。
- 文档分支：`docs/<主题>`。
- 提交格式：`feat|fix|docs|test|chore(岗位): 简短内容`。
- 不允许直接 push `main`，也不允许 force push 覆盖公共历史。

## 文件归属

| 岗位 | 主要目录 |
| --- | --- |
| R1 | `src/remote_image/modules/data/`、`tests/unit/r1/` |
| R2 | `src/remote_image/modules/flood/`、`tests/unit/r2/` |
| R3 | `src/remote_image/modules/uav/`、`src/remote_image/modules/decision/`、`tests/unit/r3/` |
| C1 | `src/remote_image/core/`、`src/remote_image/workflows/`、`schemas/`、`tests/integration/` |
| C2 | `src/remote_image/modules/damage/`、`tests/unit/c2/` |
| C3 | `app/`、`src/remote_image/modules/visualization/`、`tests/unit/c3/` |

修改 `core/contracts.py`、`schemas/v1/` 或工作流公共入口前，必须先说明字段变化、受影响模块和迁移方式，由 C1 统一接口版本。

## 禁止提交

- 原始或处理后的遥感影像、无人机照片、模型权重和 `outputs/` 运行结果；
- 虚拟环境、缓存、IDE 配置、密钥、账号和个人绝对路径；
- 无许可的数据、来源不明的底图和聊天记录；
- “最终版”“新建文件夹”等重复工程目录。

大型文件只提交 manifest，记录来源、许可、文件名、sha256、适用范围和获取方式。只有项目组明确启用 Git LFS 后才能用 LFS 上传指定大文件。

## Pull Request 最低要求

- 写明目的、负责人、修改目录和影响的上下游；
- 提供运行命令、样例输入输出和测试结果；
- UI 变更提供截图；空间结果提供小型 fixture 或可复现清单；
- CI 通过，没有误上传数据、权重、输出和绝对路径；
- 若改接口，schema、fixture、文档和迁移说明同时更新。

详细说明见 `docs/GITHUB_COLLABORATION.md`。
