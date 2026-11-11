# C3 第一阶段开发说明

`src/remote_image/modules/visualization/stage1.py` 提供 manifest 读取、GeoJSON 查询、上游统计摘要显示和离线 SVG 地图渲染。GeoTIFF 通过可选 GIS 依赖读取，渲染不访问在线底图。当前 `tests/fixtures/stage1_synthetic` 只用于开发和测试，不能作为真实灾情结果。

启动页面（安装 Streamlit 后）：

```text
streamlit run app/main.py
```

安装 UI 和 GIS 可选依赖：

```text
python -m pip install -e ".[ui,gis]"
```

运行核心测试：

```text
python -m unittest discover -s tests -p "test_*.py"
```
