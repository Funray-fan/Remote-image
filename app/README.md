# UI 目录

C3 在此维护 Streamlit 应用入口和页面。UI 只调用 `workflows` 和标准结果对象，不在页面代码中实现遥感算法或重新计算统计指标。
# C3 地图页面

从仓库根目录安装 UI/GIS 依赖后启动：

```powershell
python -m pip install -e ".[ui,gis]"
streamlit run app/main.py
```

页面默认加载 `tests/fixtures/stage1_synthetic/layer_manifest.json`，可在侧栏替换为 C1/R2 交付的本地 manifest。
