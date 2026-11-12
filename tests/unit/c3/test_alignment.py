"""Exercise the C1 v2 handoff through the actual C3 page."""

import json
from pathlib import Path
from shutil import copytree

from streamlit.testing.v1 import AppTest

from remote_image.workflows.demo import prepare_demo
from remote_image.workflows.integrated import run_case
from remote_image.modules.visualization.stage1 import load_manifest


ROOT = Path(__file__).resolve().parents[3]


def _page(root):
    from pathlib import Path
    from unittest.mock import patch
    import app.main as page

    root = Path(root)
    with (
        patch.object(page, "REPOSITORY_ROOT", root),
        patch.object(page, "DEFAULT_MANIFEST", root / "tests/fixtures/stage1_synthetic/layer_manifest.json"),
        patch.object(page, "STAGE2_FIXTURE", root / "tests/fixtures/stage2_synthetic"),
    ):
        page.main()


def test_c1_v2_output_in_stage1_and_stage2_navigation(tmp_path):
    copytree(ROOT / "tests/fixtures/stage1_synthetic", tmp_path / "tests/fixtures/stage1_synthetic",
             ignore=lambda directory, names: [name for name in names if name.startswith("tmp")])
    copytree(ROOT / "tests/fixtures/stage2_synthetic", tmp_path / "tests/fixtures/stage2_synthetic")
    result = run_case(prepare_demo(tmp_path))
    manifest = load_manifest(result / "layer_manifest.json", allowed_root=tmp_path)
    assert manifest["schema_version"] == "2.0"
    assert manifest["synthetic"] is True
    flood = next(layer for layer in manifest["layers"] if layer.id == "flood_mask")
    assert flood.palette["1"] == "#16a6b6"
    assert next(layer for layer in manifest["layers"] if layer.id == "pre_event").visible is False
    app = AppTest.from_function(_page, args=(str(tmp_path),)).run(timeout=30)
    assert not app.exception and not app.error
    assert app.sidebar.selectbox[0].value.startswith("合成联调")
    metrics = {metric.label: metric.value for metric in app.metric}
    assert float(metrics["新增水体候选面积（m²）"].replace(",", "")) == 9600
    assert metrics["交叠建筑来源对象数"] == "1"
    assert metrics["人口暴露（未知）"] == "未知"
    next(item for item in app.checkbox if item.label == "道路底图").check().run(timeout=30)
    assert not app.exception and not app.error
    assert "way:1" in app.get("iframe")[0].proto.srcdoc
    app.radio[0].set_value("阶段二 · 建筑灾损").run(timeout=30)
    assert not app.exception and not app.error
    assert "DEMO-004" in app.get("iframe")[0].proto.srcdoc
    app.radio[0].set_value("阶段一 · 洪水影响").run(timeout=30)
    assert not app.exception and not app.error
    assert app.sidebar.selectbox[0].value.startswith("合成联调")
    summary = json.loads((result / "summary.json").read_text(encoding="utf-8"))
    assert summary["metrics"]["population_exposed"] is None
