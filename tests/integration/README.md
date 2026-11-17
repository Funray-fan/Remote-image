# 集成测试

C1 维护跨模块的数据交接和阶段流水线测试。集成测试只使用 `tests/fixtures/` 中的小型样例。

阶段二测试包括 `model-manifest.schema.json` 正反例、模型动态加载/注册、权重哈希错误、参数硬限制和 `DamageResult` 内嵌结果校验。合成适配器位于 `tests/support/stage2_adapter.py`。
