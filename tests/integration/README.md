# 集成测试

`test_c1_stage2.py` 覆盖 v2 model manifest、权重哈希、模型加载器/版本注册、推理参数合并、输入适用性、结果身份和 JSON/GeoPackage 属性交接。`stage2_adapter.py` 只生成合成样例，不代表真实模型效果。

C1 维护跨模块的数据交接和阶段流水线测试。集成测试只使用 `tests/fixtures/` 中的小型样例。
