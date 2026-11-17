# C1 第二阶段：模型加载与灾损推理

本模块实现 v1.5 中 C1 第二阶段的三个入口：

```python
from remote_image.workflows.damage import load_model, register_model, run_damage
```

## 调用顺序

```python
adapter = load_model("models/manifests/damage_model.json", device="cpu")
register_model(adapter.name, adapter)
result = run_damage(request, options)
```

- `load_model` 读取并校验 `model-manifest.schema.json`，校验权重 SHA-256，动态创建 `DamageModel` 适配器。
- `register_model` 将带 manifest 的适配器注册到运行器，供 `run_damage` 按 `request.model_name` 查找。
- `run_damage` 校验 `DamageRequest`，合并推理参数，调用适配器，再校验 `DamageResult`、`damage_vector` 和 `tile_index`。

## 适配器工厂

`model_manifest.json` 中的 `adapter_entrypoint` 使用 `module:factory` 格式。工厂签名为：

```python
def build_model(manifest: ModelManifest) -> DamageModel:
    ...
```

工厂返回对象必须有 `name` 和 `predict(request, options)`。`name` 必须等于 manifest 的 `model_name`。工厂通过 `manifest.weights` 获得已解析并校验的权重路径。

## 参数合并

生效顺序固定为：

```text
manifest.inference_defaults -> InferenceOptions 非空字段
```

合并后的参数必须位于 `manifest.inference_limits` 内。最终生效值写入：

```python
result.meta.parameters["inference_options"]
```

## 结果校验

C1 在交接前检查：

- `DamageResult` 必含 `metadata`、`tile_index`，以及 `damage_vector`、`damage_mask`、`building_mask` 中至少一项；
- `model_name`、`model_version`、`event_id`、`study_area_id`、`input_asset_ids` 和任务与请求/manifest 一致；
- `confidence` 位于 `[0, 1]`，`damage_class` 使用固定枚举且属于 manifest 的 `class_map`；
- 所有 artifact 文件存在；
- `damage_vector` 和 `tile_index` 的 JSON/GeoJSON 直接校验 schema；GeoPackage 读取属性表完成相同字段校验，空间位置检查仍由 R2 负责。

错误统一使用 `PipelineError`，包含 `code`、`message`、`module`、`details`。模型加载失败返回 `MODEL_LOAD_FAILED`；请求或参数越界返回 `INPUT_INVALID`/`INPUT_MISSING`；适配器执行或结果不合格返回 `PROCESSING_FAILED`。

## 合成验收样例

测试用 manifest 位于 `tests/fixtures/contracts/model_manifest_valid.json`，适配器工厂位于 `tests/support/stage2_adapter.py`。样例只验证接口，不表示真实灾损结论。

```powershell
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
```
