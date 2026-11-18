"""C1 runtime handoff through real R2 reports and C3 public/UI boundaries."""

import json
import unittest
from dataclasses import replace
from pathlib import Path

from remote_image.core.contracts import DamageResult, InferenceOptions
from remote_image.core.errors import ErrorCode, PipelineError
from remote_image.core.serialization import from_payload
from remote_image.modules.visualization.interfaces import render_damage_layer, show_building_detail
from remote_image.modules.visualization.model_evidence import load_model_evidence
from remote_image.modules.visualization.public_stage2 import create_damage_map_handle
from remote_image.modules.visualization.stage1 import VisualizationInputError
from remote_image.modules.visualization.stage2 import load_damage_result
from remote_image.workflows.c3_stage2_demo import run_synthetic_handoff

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests/fixtures/stage2_synthetic"


class C1Stage2AlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result_path = run_synthetic_handoff(ROOT, InferenceOptions(tile_size_px=512, batch_size=1))
        cls.qa_path = cls.result_path.parent / "spatial_qa.json"

    def test_runtime_result_r2_report_and_public_queries(self):
        result = load_damage_result(self.result_path, allowed_root=ROOT, spatial_qa_path=self.qa_path)
        self.assertEqual(len(result.features), 6)
        self.assertEqual(result.model_version, "2.0.0")
        self.assertTrue(result.synthetic)
        self.assertEqual(result.parameters["inference_options"]["tile_size_px"], 512)
        self.assertEqual(result.parameters["inference_options"]["overlap_ratio"], .2)
        self.assertEqual(result.spatial_qa["status"], "pass")
        public = from_payload(DamageResult, json.loads(self.result_path.read_text(encoding="utf-8")))
        handle = create_damage_map_handle(result.event_id, allowed_root=ROOT,
            base_dir=self.result_path.parent, spatial_qa_path=self.qa_path)
        layer = render_damage_layer(result.event_id, public, handle, 0)
        self.assertEqual(show_building_detail(result.event_id, layer, "DEMO-004").properties["confidence"], .94)
        detail = show_building_detail(result.event_id, layer, "DEMO-005")
        self.assertIsNone(detail.properties["confidence"])
        self.assertTrue(detail.properties["reason"])

    def test_package_hash_identity_and_class_checks(self):
        result = load_damage_result(self.result_path, allowed_root=ROOT, spatial_qa_path=self.qa_path)
        evidence = load_model_evidence(FIXTURE / "model_manifest.json", result, allowed_root=ROOT)
        self.assertEqual(evidence["model_version"], result.model_version)
        with self.assertRaises(PipelineError) as error:
            load_model_evidence(FIXTURE / "model_manifest_bad_hash.json", result, allowed_root=ROOT)
        self.assertEqual(error.exception.code, ErrorCode.MODEL_LOAD_FAILED)
        with self.assertRaisesRegex(VisualizationInputError, "版本"):
            load_model_evidence(FIXTURE / "model_manifest.json", replace(result, model_version="other"), allowed_root=ROOT)

    def test_ui_runs_c1_then_displays_r2_and_keeps_display_threshold_separate(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(ROOT / "app/main.py")).run(timeout=30)
        app.radio[0].set_value("阶段二 · 建筑灾损").run(timeout=30)
        app.radio[1].set_value("C1 合成联调").run(timeout=30)
        self.assertFalse(app.exception)
        next(item for item in app.button if item.label == "运行 C1→R2→C3 合成联调").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertTrue(any("C1 模型包校验通过" in item.value for item in app.success))
        self.assertTrue(any("R2 空间质检：pass" in item.value for item in app.success))
        self.assertEqual({item.label: item.value for item in app.metric}, {"建筑总数": "6", "当前显示": "6"})
        path = Path(app.session_state["c1_demo_result"])
        before = path.read_bytes()
        app.slider[0].set_value(.9).run(timeout=30)
        self.assertFalse(app.error)
        self.assertEqual(app.metric[1].value, "2")
        self.assertEqual(path.read_bytes(), before)
        self.assertIn("function zoomMap", app.get("iframe")[0].proto.srcdoc)

    def test_ui_model_package_error_keeps_map_available(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(ROOT / "app/main.py")).run(timeout=30)
        app.radio[0].set_value("阶段二 · 建筑灾损").run(timeout=30)
        app.radio[1].set_value("本地推理结果").run(timeout=30)
        app.text_input[0].set_value(str(self.result_path))
        app.text_input[1].set_value(str(self.qa_path))
        next(item for item in app.text_input if item.label == "C1 ModelManifest 路径（可选）").set_value(str(FIXTURE / "model_manifest_bad_hash.json"))
        app.run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(any("MODEL_LOAD_FAILED" in item.value for item in app.error))
        self.assertEqual(app.metric[0].value, "6")
