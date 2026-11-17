# C1 第二阶段：模型加载与灾损推理

本实现基于 `feature/c1-stage1-integration` 的 v2.0 公共契约，不改动 `core/contracts.py` 或 `schemas/v2/` 字段。

## 入口

```python
from remote_image.workflows.damage import (
    load_model,
    register_model,
    register_model_loader,
    run_damage,
)

register_model_loader(model_name, model_version, loader)
adapter = load_model("models/example/model_manifest.json", device="cpu")
register_model(adapter.name, adapter.version, adapter)
result = run_damage(request, options)
```

C2 的 `loader(manifest, device)` 负责把权重格式转换成 `DamageModel`。该注册步骤隔离了 ONNX、PyTorch、TorchScript 和远程服务实现，v2 manifest 无需增加 C2 私有入口字段。已经构造好的适配器也可以直接传给 `register_model`，但只有通过 `load_model` 加载的适配器会自动合并 manifest 默认参数。

## Manifest 校验

`load_model` 校验：

- `ModelManifest` 符合 `schemas/v2/model-manifest.schema.json`；
- 权重和评估引用是非绝对、无 `..` 的项目内路径，且文件存在；
- `weights_sha256` 为 64 位十六进制并与文件内容一致；
- 输入传感器、波段、像元尺寸、切片尺寸和类别映射语义有效；
- `class_map` 与 `object_aggregation.damage_class_map` 一致；
- 默认参数、允许设备和推理参数上限一致。

## 参数合并

有效参数顺序为：

```text
manifest.inference_defaults
    -> request InferenceOptions 的非空字段
    -> input_spec.tile_size_px（仅当切片尺寸仍未确定）
```

合并结果写入 `DamageResult.meta.parameters["inference_options"]`，并受 `inference_limits` 和 `allowed_tile_sizes_px` 硬限制。

## 交接校验

调用模型前检查模型名称/版本、任务、灾前影像要求、输入文件、传感器、波段、像元尺寸和灾前灾后 CRS。

调用模型后检查：

- `DamageResult`、模型身份、事件、研究区、输入血缘和任务；
- `tile_index`、`metadata` 以及建筑灾损必需的 `damage_vector`；
- GeoJSON/JSON 或 GeoPackage 的逐建筑和切片属性；
- `building_id`/`tile_id` 唯一性，类别来自 manifest，结果模型版本与请求一致；
- artifact 文件存在，未知 artifact 键被拒绝。

空间覆盖、投影精度和切片边缘仍由 R2 的独立空间 QA 负责。

## 错误码

`PipelineError` 统一返回 `INPUT_MISSING`、`INPUT_INVALID`、`MODEL_LOAD_FAILED`、`MODEL_NOT_REGISTERED`、`PROCESSING_FAILED` 或 `RESULT_INVALID`。

## 合成验收

`tests/fixtures/stage2_synthetic/` 和 `tests/integration/stage2_adapter.py` 只验证接口，不包含真实模型或真实灾损结论：

```powershell
$env:PYTHONPATH = "src;."
python -m unittest tests.integration.test_c1_stage2 -v
```
