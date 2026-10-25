# 本地数据目录

本目录中的影像、无人机照片和处理数据不提交 Git。建议本地使用：

```text
data/raw/<event_id>/
data/external/<dataset_name>/
data/processed/<event_id>/
data/manifests/
```

只允许把不含受限数据的清单提交到 `data/manifests/`。清单应记录来源、许可、时间、覆盖、sha256、限制和获取方式。
