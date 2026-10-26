"""v1.6 公共接口的 v2 契约测试；所有样例均为隔离的合成数据。

这些测试核对跨模块数据边界，不代表真实洪水、建筑损毁或路线效果。
"""

from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime
from pathlib import Path

from remote_image.core import contracts
from remote_image.core.serialization import from_payload, to_payload
from remote_image.core.validation import validate_contract, validate_payload
from remote_image.modules.damage import check_adapter_contract


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "contracts_v2"


def fixture_cases() -> list[dict]:
    return json.loads((FIXTURES / "_manifest.json").read_text(encoding="utf-8"))["cases"]


def valid_payload(schema_name: str) -> dict:
    """每次读取独立副本，使反例变异不会污染其他测试。"""
    for case in fixture_cases():
        if case["schema"] == schema_name and case["valid"]:
            return json.loads((FIXTURES / case["file"]).read_text(encoding="utf-8"))
    raise AssertionError(f"缺少 {schema_name} 正例")


def nested_result(schema_name: str, request: dict) -> dict:
    result = valid_payload(schema_name)
    result.pop("schema_version")
    result["meta"]["event_id"] = request["event_id"]
    result["meta"]["study_area_id"] = request["study_area"]["identifier"]
    return result


class ContractV2FixtureTests(unittest.TestCase):
    def test_manifest_fixtures_follow_public_validation(self) -> None:
        cases = fixture_cases()
        self.assertTrue(cases, "契约样例清单不能为空")
        self.assertTrue(any(not case["valid"] for case in cases), "必须包含反例")
        for case in cases:
            with self.subTest(schema=case["schema"], file=case["file"]):
                payload = json.loads((FIXTURES / case["file"]).read_text(encoding="utf-8"))
                if case["valid"]:
                    validate_payload(case["schema"], payload)
                else:
                    with self.assertRaises(ValueError):
                        validate_payload(case["schema"], payload)

    def test_major_handoffs_round_trip_paths_tuples_and_timestamps(self) -> None:
        cases = (
            ("flood-request", contracts.FloodRequest),
            ("damage-request", contracts.DamageRequest),
            ("decision-request", contracts.DecisionRequest),
            ("layer-manifest", contracts.LayerManifest),
        )
        for schema_name, contract_type in cases:
            with self.subTest(schema=schema_name):
                source = valid_payload(schema_name)
                value = from_payload(contract_type, source)
                validate_contract(value)
                encoded = to_payload(value)
                # JSON 编解码模拟交接文件，避免仅比较内存中的 dataclass。
                decoded = from_payload(contract_type, json.loads(json.dumps(encoded)))
                self.assertEqual(value, decoded)
                self.assertEqual(encoded["schema_version"], "2.0")

        damage = from_payload(contracts.DamageRequest, valid_payload("damage-request"))
        self.assertIsInstance(damage.post_event.path, Path)
        self.assertIsInstance(damage.post_event.bands, tuple)

    def test_default_inference_options_keep_explicit_null_fields(self) -> None:
        payload = to_payload(contracts.InferenceOptions())
        self.assertEqual(
            payload,
            {
                "schema_version": "2.0",
                "tile_size_px": None,
                "overlap_ratio": None,
                "confidence_threshold": None,
                "device": None,
                "batch_size": None,
            },
        )
        validate_payload("inference-options", payload)

    def test_v1_is_not_silently_loaded_as_v2(self) -> None:
        payload = valid_payload("damage-request")
        payload["schema_version"] = "1.0"
        with self.assertRaises(ValueError):
            from_payload(contracts.DamageRequest, payload)

    def test_unknown_field_is_rejected_at_handoff(self) -> None:
        payload = valid_payload("damage-request")
        payload["unagreed_parameter"] = True
        with self.assertRaises(ValueError):
            validate_payload("damage-request", payload)

    def test_schema_name_cannot_escape_the_schema_directory(self) -> None:
        with self.assertRaises(ValueError):
            validate_payload("../contracts", {})

    def test_naive_datetime_cannot_be_serialized_as_known_timezone(self) -> None:
        with self.assertRaises(ValueError):
            to_payload({"observed_at": datetime(2026, 10, 26, 12, 0)})


class ContractV2SemanticTests(unittest.TestCase):
    def test_sar_threshold_keys_must_match_selected_polarizations(self) -> None:
        base = valid_payload("flood-options")
        base.update(
            polarizations=["VV", "VH"],
            polarization_rule="all",
            post_thresholds_db={"VV": -16.0, "VH": -23.0},
            pre_water_thresholds_db={"VV": -15.0, "VH": -22.0},
        )
        validate_payload("flood-options", base)
        for threshold_field in ("post_thresholds_db", "pre_water_thresholds_db"):
            invalid = copy.deepcopy(base)
            invalid[threshold_field].pop("VH")
            with self.subTest(field=threshold_field), self.assertRaises(ValueError):
                validate_payload("flood-options", invalid)

        invalid = copy.deepcopy(base)
        invalid["polarization_rule"] = "single"
        with self.assertRaises(ValueError):
            validate_payload("flood-options", invalid)

    def test_flood_requires_pre_event_and_matching_study_area(self) -> None:
        base = valid_payload("flood-request")
        validate_payload("flood-request", base)
        missing_pre = copy.deepcopy(base)
        missing_pre["inputs"]["pre_event"] = None
        with self.assertRaises(ValueError):
            validate_payload("flood-request", missing_pre)
        wrong_area = copy.deepcopy(base)
        wrong_area["inputs"]["study_area_id"] = "another_synthetic_area"
        with self.assertRaises(ValueError):
            validate_payload("flood-request", wrong_area)

    def test_gcp_selection_requires_a_control_point_reference(self) -> None:
        payload = valid_payload("orthomosaic-request")
        payload["control_source"] = "GCP"
        payload["ground_control_points"] = "synthetic/control_points.csv"
        validate_payload("orthomosaic-request", payload)
        payload["ground_control_points"] = None
        with self.assertRaises(ValueError):
            validate_payload("orthomosaic-request", payload)

    def test_flood_is_not_a_building_model_task(self) -> None:
        payload = valid_payload("damage-request")
        payload["task"] = "flood_mapping"
        with self.assertRaises(ValueError):
            validate_payload("damage-request", payload)

    def test_damage_model_version_is_required(self) -> None:
        for replacement in (None, ""):
            payload = valid_payload("damage-request")
            payload["model_version"] = replacement
            with self.subTest(value=replacement), self.assertRaises(ValueError):
                validate_payload("damage-request", payload)

    def test_building_damage_cannot_complete_with_only_a_mask(self) -> None:
        payload = valid_payload("damage-result")
        payload["meta"]["method"] = "building_damage"
        payload["artifacts"].pop("damage_vector", None)
        payload["artifacts"]["building_mask"] = "synthetic/building_mask.tif"
        with self.assertRaises(ValueError):
            validate_payload("damage-result", payload)

    def test_decision_rejects_mixed_events_and_study_areas(self) -> None:
        for result_field, schema_name in (
            ("flood_result", "flood-result"),
            ("review_result", "review-result"),
            ("damage_results", "damage-result"),
        ):
            base = valid_payload("decision-request")
            result = nested_result(schema_name, base)
            base[result_field] = [result] if result_field == "damage_results" else result
            validate_payload("decision-request", base)
            for meta_field in ("event_id", "study_area_id"):
                invalid = copy.deepcopy(base)
                target = invalid[result_field][0] if result_field == "damage_results" else invalid[result_field]
                target["meta"][meta_field] = "another_synthetic_case"
                with self.subTest(result=result_field, field=meta_field), self.assertRaises(ValueError):
                    validate_payload("decision-request", invalid)

    def test_map_manifest_rejects_a_layer_from_another_event(self) -> None:
        payload = valid_payload("layer-manifest")
        self.assertTrue(payload["layers"], "地图清单正例须含图层")
        payload["layers"][0]["event_id"] = "another_synthetic_event"
        with self.assertRaises(ValueError):
            validate_payload("layer-manifest", payload)

    def test_confirmed_blocked_and_unknown_policies_remain_separate(self) -> None:
        payload = valid_payload("route-options")
        payload["blocked_policy"] = "exclude"
        payload["unknown_policy"] = "penalize"
        payload["unknown_penalty_factor"] = 10.0
        validate_payload("route-options", payload)
        payload["blocked_policy"] = "penalize"
        with self.assertRaises(ValueError):
            validate_payload("route-options", payload)

    def test_priority_weights_are_nonnegative_and_sum_to_one(self) -> None:
        for weights in (
            {"damage": 0.2, "population": 0.2, "access": 0.2},
            {"damage": -0.1, "population": 0.5, "access": 0.6},
            {"damage": 0.5, "population": 0.5},
        ):
            payload = valid_payload("priority-spec")
            payload["weights"] = weights
            with self.subTest(weights=weights), self.assertRaises(ValueError):
                validate_payload("priority-spec", payload)

    def test_review_allows_empty_samples_but_caps_each_object_type(self) -> None:
        base = valid_payload("review-spec")
        base.update(sample_n=0, road_sample_n=0)
        validate_payload("review-spec", base)
        for field, value in (("sample_n", 201), ("sample_n", -1), ("road_sample_n", 51)):
            payload = copy.deepcopy(base)
            payload[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_payload("review-spec", payload)

    def test_scene_or_image_pair_cannot_leak_across_dataset_splits(self) -> None:
        base = valid_payload("dataset-manifest")
        self.assertTrue(base["items"], "数据集正例须含样本")
        train = copy.deepcopy(base["items"][0])
        train.update(sample_id="synthetic_train", scene_id="scene_train", image_pair_id="pair_train",
                     group_id="group_train", split="train")
        validation = copy.deepcopy(train)
        validation.update(sample_id="synthetic_val", scene_id="scene_val", image_pair_id="pair_val",
                          group_id="group_val", split="val", post_event_path="synthetic/val_post.tif",
                          pre_event_path="synthetic/val_pre.tif", label_path="synthetic/val_labels.json")
        base["items"] = [train, validation]
        base["spatial_overlap_checked"] = True
        base["overlap_report_path"] = "synthetic/overlap_report.json"
        validate_payload("dataset-manifest", base)
        for grouping_key in ("group_id", "scene_id", "image_pair_id"):
            invalid = copy.deepcopy(base)
            invalid["items"][1][grouping_key] = invalid["items"][0][grouping_key]
            with self.subTest(key=grouping_key), self.assertRaises(ValueError):
                validate_payload("dataset-manifest", invalid)

    def test_pending_review_does_not_claim_an_open_road(self) -> None:
        payload = valid_payload("review-record")
        payload.update(object_type="road", review_status="pending", road_status="open",
                       damage_class=None, confirmation="unconfirmed", reviewed_at=None)
        with self.assertRaises(ValueError):
            validate_payload("review-record", payload)

    def test_unknown_building_prediction_keeps_null_and_a_reason(self) -> None:
        base = valid_payload("damage-vector")
        self.assertTrue(base["features"], "逐建筑正例须含一个对象")
        properties = base["features"][0]["properties"]
        properties.update(damage_class="un-classified", confidence=None,
                          reason="synthetic fixture: no valid prediction pixels")
        validate_payload("damage-vector", base)
        missing_reason = copy.deepcopy(base)
        missing_reason["features"][0]["properties"]["reason"] = ""
        with self.assertRaises(ValueError):
            validate_payload("damage-vector", missing_reason)
        false_class = copy.deepcopy(base)
        false_class["features"][0]["properties"]["damage_class"] = "no-damage"
        with self.assertRaises(ValueError):
            validate_payload("damage-vector", false_class)

    def test_building_confidence_stays_in_unit_interval(self) -> None:
        for confidence in (-0.01, 1.01):
            payload = valid_payload("damage-vector")
            payload["features"][0]["properties"]["confidence"] = confidence
            with self.subTest(confidence=confidence), self.assertRaises(ValueError):
                validate_payload("damage-vector", payload)


class AdapterV2IdentityTests(unittest.TestCase):
    """版本、事件及研究区是请求和结果之间的约束，须在适配器边界测试。"""

    def make_pair(self) -> tuple:
        request_payload = valid_payload("damage-request")
        request = from_payload(contracts.DamageRequest, request_payload)
        result_payload = valid_payload("damage-result")
        result_payload["model_name"] = request.model_name
        result_payload["model_version"] = request.model_version
        result_payload["meta"].update(
            event_id=request.event_id,
            study_area_id=request.study_area.identifier,
            method=request.task,
            input_asset_ids=[request.post_event.asset_id]
            + ([request.pre_event.asset_id] if request.pre_event is not None else []),
        )
        return request, result_payload

    @staticmethod
    def adapter(request, result_payload):
        class SyntheticAdapter:
            name = request.model_name
            version = request.model_version

            def predict(self, request, options=None):
                return from_payload(contracts.DamageResult, result_payload)

        return SyntheticAdapter()

    def test_matching_synthetic_adapter_passes_without_real_model_files(self) -> None:
        request, result_payload = self.make_pair()
        report = check_adapter_contract(self.adapter(request, result_payload), request, validate_artifacts=False)
        self.assertTrue(report.passed, report.errors)

    def test_returned_model_name_and_version_must_match_request(self) -> None:
        for field in ("model_name", "model_version"):
            request, result_payload = self.make_pair()
            result_payload[field] = "different_synthetic_model"
            report = check_adapter_contract(self.adapter(request, result_payload), request, validate_artifacts=False)
            with self.subTest(field=field):
                self.assertFalse(report.passed)
                self.assertTrue(report.errors)

    def test_returned_event_and_area_must_match_request(self) -> None:
        for field in ("event_id", "study_area_id"):
            request, result_payload = self.make_pair()
            result_payload["meta"][field] = "another_synthetic_case"
            report = check_adapter_contract(self.adapter(request, result_payload), request, validate_artifacts=False)
            with self.subTest(field=field):
                self.assertFalse(report.passed)

    def test_returned_input_lineage_must_include_requested_post_asset(self) -> None:
        request, result_payload = self.make_pair()
        result_payload["meta"]["input_asset_ids"] = ["another_synthetic_asset"]
        report = check_adapter_contract(self.adapter(request, result_payload), request, validate_artifacts=False)
        self.assertFalse(report.passed)


if __name__ == "__main__":
    unittest.main()
