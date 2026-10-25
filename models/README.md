# 本地模型目录

模型权重不直接提交 Git。建议本地使用 `models/<model_name>/<version>/`，并在 `models/manifests/` 提交模型清单。清单至少记录任务、版本、权重 sha256、输入波段、像元尺寸范围、归一化、类别表和依赖版本。
