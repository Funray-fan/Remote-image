# 阶段二模型 fixture 约定

`check_adapter_contract` 不要求提前训练 U-Net 或准备真实灾区推理结果。它只验证适配器能否遵守公共接口。

## 预先固定的内容

- `DamageRequest` 必须包含 `event_id`、`study_area`、灾后资产、模型名称和任务；
- `DamageResult.artifacts` 必须包含 `metadata`、`tile_index`，以及 `damage_vector`、`damage_mask`、`building_mask` 中至少一项；
- `damage_class` 只允许 `no-damage`、`minor-damage`、`major-damage`、`destroyed`、`un-classified`；
- `confidence` 为 0 到 1 的数值；
- `ResultMeta.event_id`、`study_area_id` 和 `input_asset_ids` 必须与请求一致；
- 非法类别、缺字段和未知 artifact 键必须被拒绝。

## 真实训练结果何时加入

阶段二模型形成后，C2 另行提交模型 manifest、独立测试集评估报告和一个小型真实推理样例。真实样例只能证明模型实现与性能，不能临时改变公共键名和类别枚举；确需改变时走 schema 版本升级流程。
