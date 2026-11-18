"""C3 consumes R3 evidence and public C1/C2 results without confusing their roles."""

import json
import tempfile
import unittest
from pathlib import Path
from shutil import copytree

from remote_image.core.contracts import DamageResult, FeatureDetail, MapHandle
from remote_image.core.serialization import from_payload
from remote_image.modules.visualization.context import load_context_view
from remote_image.modules.visualization.interfaces import render_damage_layer, show_building_detail
from remote_image.modules.visualization.public_stage2 import create_damage_map_handle
from remote_image.modules.visualization.stage1 import VisualizationInputError

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests/fixtures/stage2_synthetic"
EVENT = "demo-flood-2023"


class ContextIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = copytree(FIXTURE, self.root / "stage2_synthetic")
        copytree(FIXTURE.parent / "stage1_synthetic", self.root / "stage1_synthetic",
                 ignore=lambda directory, names: [name for name in names if name.startswith("tmp")])
        self.context = self.data / "context_layers.json"
        self.qa = self.data / "context_qa.json"

    def read(self, **kwargs):
        return load_context_view(self.context, event_id=EVENT, allowed_root=self.root, **kwargs)

    def change(self, path, callback):
        data = json.loads(path.read_text(encoding="utf-8"))
        callback(data)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_r3_warning_is_visible_and_layers_remain_optional(self):
        view = self.read(study_area_id="demo-area")
        self.assertEqual(view.report["status"], "warning")
        self.assertEqual(len(view.layers), 2)
        self.assertTrue(all(not layer.visible for layer in view.layers))
        self.assertEqual(view.sources[0]["观测日期"], "未知")
        self.assertTrue(any("覆盖未验证" in note for note in view.notices))
        self.assertTrue(any("不能替代 R2" in note for note in view.notices))

    def test_other_event_or_study_area_is_rejected(self):
        with self.assertRaises(VisualizationInputError):
            self.read(study_area_id="other")
        self.change(self.context, lambda data: data.update(event_id="other"))
        with self.assertRaises(VisualizationInputError):
            self.read()

    def test_missing_report_does_not_claim_review_or_overlay(self):
        self.qa.unlink()
        view = self.read()
        self.assertIsNone(view.report)
        self.assertFalse(view.layers)
        self.assertTrue(view.sources)

    def test_report_binding_and_event_checks_required(self):
        original = self.qa.read_text(encoding="utf-8")
        for mutate in (
            lambda data: data.update(artifacts={}),
            lambda data: data["checks"][0].update(actual="other"),
            lambda data: data.update(checks=[]),
        ):
            self.qa.write_text(original, encoding="utf-8")
            self.change(self.qa, mutate)
            with self.subTest(mutate=mutate), self.assertRaises(VisualizationInputError):
                self.read()

    def test_failure_checks_block_background_even_if_overall_warning(self):
        def fail(data):
            data["checks"].append(dict(name="buildings.geometry", status="fail",
                expected=True, actual=False, message="invalid geometry"))
        self.change(self.qa, fail)
        view = self.read()
        self.assertFalse(view.layers)
        self.assertTrue(any("复核失败" in note for note in view.notices))

    def test_source_paths_cannot_escape_root(self):
        self.change(self.context, lambda data: data["layers"].update(buildings="../../outside.geojson"))
        with self.assertRaises(VisualizationInputError):
            self.read()

    def test_public_contract_render_and_query_isolate_maps(self):
        result = from_payload(DamageResult, json.loads((self.data / "damage_result.json").read_text()))
        first = create_damage_map_handle(EVENT, allowed_root=self.root, base_dir=self.data)
        second = create_damage_map_handle(EVENT, allowed_root=self.root, base_dir=self.data)
        self.assertIsInstance(first, MapHandle)
        layer = render_damage_layer(EVENT, result, first, 0)
        other_layer = render_damage_layer(EVENT, result, second, .9)
        self.assertNotEqual(layer, other_layer)
        detail = show_building_detail(EVENT, layer, "DEMO-003")
        self.assertIsInstance(detail, FeatureDetail)
        self.assertEqual(detail.properties["model_version"], result.model_version)
        detail.properties["confidence"] = 0
        self.assertEqual(show_building_detail(EVENT, layer, "DEMO-003").properties["confidence"], .82)
        with self.assertRaises(VisualizationInputError):
            show_building_detail(EVENT, other_layer, "DEMO-003")
        with self.assertRaises(VisualizationInputError):
            show_building_detail("other", layer, "DEMO-003")
        with self.assertRaises(VisualizationInputError):
            render_damage_layer("other", result, first, 0)
        with self.assertRaises(VisualizationInputError):
            render_damage_layer(EVENT, result, first, 2)
        self.assertEqual(show_building_detail(EVENT, layer, "DEMO-003").properties["confidence"], .82)
        render_damage_layer(EVENT, result, first, .9)
        self.assertEqual([item.id for item in first.state.layers], [layer])
        with self.assertRaises(VisualizationInputError):
            show_building_detail(EVENT, layer, "DEMO-003")

    def test_public_contract_requires_r2_for_real_results(self):
        payload = json.loads((self.data / "damage_result.json").read_text())
        payload["meta"]["parameters"] = {}
        (self.data / "metadata.json").write_text("{}")
        result = from_payload(DamageResult, payload)
        handle = create_damage_map_handle(EVENT, allowed_root=self.root, base_dir=self.data)
        # A valid R3 report cannot substitute for missing R2 spatial_qa.json.
        with self.assertRaisesRegex(VisualizationInputError, "spatial_qa.json"):
            render_damage_layer(EVENT, result, handle, 0)
