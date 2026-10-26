"""Schema 与跨字段校验。此处不替代栅格/GIS 质检或真实模型效果验收。"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from remote_image.core.serialization import to_payload


class ContractValidationError(ValueError):
    """交接对象不满足公共契约。"""


def schema_filename(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.schema\.json|\.json)?", name):
        raise ContractValidationError(f"无效 schema 名称: {name}")
    name = name.removesuffix(".schema.json").removesuffix(".json")
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name)
    return name.replace("_", "-").lower() + ".schema.json"


def _schema_path(name: str) -> Path:
    filename = schema_filename(name)
    # 包内数据支持 wheel 安装；源码检出亦可直接运行。
    packaged = Path(__file__).resolve().parents[1] / "schema_data" / "v2" / filename
    source = Path(__file__).resolve().parents[3] / "schemas" / "v2" / filename
    for candidate in (packaged, source):
        if candidate.is_file():
            return candidate
    raise ContractValidationError(f"未知 v2 schema: {name}")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractValidationError(message)


def _semantics(value: Any, location: str = "$") -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            _semantics(item, f"{location}[{index}]")
        return
    if not isinstance(value, dict):
        if isinstance(value, float):
            _require(math.isfinite(value), f"{location}: 不允许 NaN/Infinity")
        return
    v = value

    def check(condition: bool, text: str) -> None:
        _require(condition, f"{location}: {text}")

    if {"polarizations", "post_thresholds_db", "pre_water_thresholds_db"} <= v.keys():
        pols = v["polarizations"]
        check(bool(pols) and len(pols) == len(set(pols)), "polarizations 必须非空且不重复")
        check(set(pols) == set(v["post_thresholds_db"]) == set(v["pre_water_thresholds_db"]), "极化与两套阈值的键必须一致")
        check(v["polarization_rule"] != "single" or len(pols) == 1, "single 只能使用一个极化")
    if {"inputs", "options", "study_area", "event_id"} <= v.keys():
        inputs = v["inputs"]
        check(inputs["pre_event"] is not None, "洪水基线必须提供灾前影像")
        check(inputs["study_area_id"] == v["study_area"]["identifier"], "PreparedInputs 研究区不一致")
        if inputs["pre_event"] is not None:
            pre, post = inputs["pre_event"], inputs["post_event"]
            check(pre["coordinate_reference_system"] == post["coordinate_reference_system"], "灾前灾后 CRS 不一致")
            for asset in (pre, post):
                check(set(v["options"]["polarizations"]) <= set(asset["bands"]), "所选极化缺少影像波段")
    if {"control_source", "ground_control_points"} <= v.keys():
        check(v["control_source"] != "GCP" or v["ground_control_points"] is not None, "GCP 模式必须提供控制点")
        check(v["control_source"] != "none" or v["ground_control_points"] is None, "none 模式不能同时声称使用 GCP")
    if {"pixel_size_min_m", "pixel_size_max_m"} <= v.keys():
        check(0 < v["pixel_size_min_m"] <= v["pixel_size_max_m"], "像元尺寸范围无效")
    if {"speckle_method", "speckle_window_px"} <= v.keys():
        window = v["speckle_window_px"]
        check(v["speckle_method"] != "refined_lee" or (window is not None and window >= 3 and window % 2 == 1), "refined_lee 需要大于等于3的奇数窗口")
    if {"grid_size_m", "weights", "population_reference"} <= v.keys():
        weights = v["weights"]
        check(set(weights) == {"damage", "population", "access"}, "priority 权重必须为 damage/population/access")
        check(all(x >= 0 for x in weights.values()) and math.isclose(sum(weights.values()), 1.0, abs_tol=1e-8), "priority 权重非负且和为1")
        check(v["grid_size_m"] == 1000 and v["population_reference"] > 0, "本版使用1km格网和正人口参照值")
    if {"route_options", "study_area", "damage_results"} <= v.keys():
        results = [v.get("flood_result"), v.get("review_result"), *v["damage_results"]]
        for result in filter(None, results):
            check(result["meta"]["event_id"] == v["event_id"], "不能混用不同事件的结果")
            check(result["meta"]["study_area_id"] == v["study_area"]["identifier"], "不能混用不同研究区的结果")
    if {"blocked_policy", "unknown_policy"} <= v.keys():
        check(v["blocked_policy"] == "exclude", "确认阻断道路必须排除")
        check(v["unknown_penalty_factor"] >= 1, "未知道路惩罚因子必须大于等于1")
    if {"layers", "event_id"} <= v.keys() and isinstance(v["layers"], list):
        check(all(item["event_id"] == v["event_id"] for item in v["layers"]), "图层清单不能混用事件")
        ids = [item["layer_id"] for item in v["layers"]]
        check(len(ids) == len(set(ids)), "layer_id 不能重复")
    if {"sources", "event_id", "target_crs"} <= v.keys():
        check(v["sources"]["event_id"] == v["event_id"], "ContextSources 事件不一致")
        check(set(v["layers"]) == set(v["sources"]["layers"]), "每个背景图层必须有对应来源")
    if {"sample_n", "road_sample_n"} <= v.keys():
        check(0 <= v["sample_n"] <= 200 and 0 <= v["road_sample_n"] <= 50, "人工核查数量超出上限")
        if "sample_ids" in v:
            check(len(set(v["sample_ids"])) == len(v["sample_ids"]) == v["sample_n"] <= v["eligible_count"], "建筑样本ID、数量或有效数不一致")
            check(len(set(v["road_sample_ids"])) == len(v["road_sample_ids"]) == v["road_sample_n"] <= v["road_eligible_count"], "道路样本ID、数量或有效数不一致")
    if {"model_name", "model_version"} <= v.keys():
        check(isinstance(v["model_name"], str) and bool(v["model_name"].strip()), "model_name 不能为空")
        check(isinstance(v["model_version"], str) and bool(v["model_version"].strip()), "model_version 不能为空")
    if {"model_name", "model_version", "artifacts", "meta"} <= v.keys():
        keys = set(v["artifacts"])
        check(keys <= {"damage_vector", "damage_mask", "building_mask", "tile_index", "metadata"}, "未知灾损产物键")
        check({"tile_index", "metadata"} <= keys, "灾损结果缺少 tile_index/metadata")
        if v["meta"]["method"] == "building_damage":
            check("damage_vector" in keys, "建筑灾损必须交逐栋 damage_vector")
    if {"confidence", "damage_class"} <= v.keys() and v["confidence"] is None:
        check(v["damage_class"] == "un-classified" and bool(v.get("reason")), "confidence=null 时必须 un-classified 并给出 reason")
    if {"object_type", "review_status", "road_status", "damage_class"} <= v.keys():
        if v["object_type"] == "road":
            check(v["damage_class"] is None, "道路核查不能填写建筑损毁等级")
            check(v["review_status"] == "reviewed" or v["road_status"] is None, "未完成道路核查不能声明通行状态")
        else:
            check(v["road_status"] is None, "建筑核查不能填写道路状态")
    if {"items", "split_strategy", "dataset_name"} <= v.keys():
        seen = {key: {} for key in ("sample_id", "group_id", "scene_id", "image_pair_id")}
        sample_ids: set[str] = set()
        for item in v["items"]:
            check(item["sample_id"] not in sample_ids, "sample_id 不能重复")
            sample_ids.add(item["sample_id"])
            for key, groups in seen.items():
                old = groups.setdefault(item[key], item["split"])
                check(old == item["split"], f"{key} 跨 train/val/test，存在泄漏")
        check(not v["spatial_overlap_checked"] or v["overlap_report_path"] is not None, "空间重叠检查必须附报告")
    if {"started_at", "finished_at"} <= v.keys():
        from datetime import datetime
        check(datetime.fromisoformat(v["finished_at"].replace("Z", "+00:00")) >= datetime.fromisoformat(v["started_at"].replace("Z", "+00:00")), "结束时间早于开始时间")
    if {"status", "checks", "metrics", "artifacts"} <= v.keys():
        check(v["status"] != "pass" or all(item["status"] != "fail" for item in v["checks"]), "包含失败检查的报告不能为 pass")
    if {"min_zoom", "max_zoom"} <= v.keys() and v["min_zoom"] is not None and v["max_zoom"] is not None:
        check(v["min_zoom"] <= v["max_zoom"], "min_zoom 不能大于 max_zoom")
    if {"reference_available", "metrics"} <= v.keys() and not v["reference_available"]:
        check(all(v["metrics"].get(key) is None for key in ("iou", "f1", "precision", "recall")), "没有真值不能填写定量精度")
    for name, item in v.items():
        _semantics(item, f"{location}.{name}")


def validate_payload(schema_name: str, payload: dict[str, Any]) -> None:
    """验证 v2 JSON；失败抛 ContractValidationError，不访问远端 schema。"""
    schema = json.loads(_schema_path(schema_name).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload), key=lambda e: str(list(e.path)))
    if errors:
        first = errors[0]
        raise ContractValidationError(f"{schema_name} {list(first.path)}: {first.message}")
    _semantics(payload)


def validate_contract(value: Any) -> None:
    try:
        payload = to_payload(value)
    except (ValueError, TypeError) as error:
        raise ContractValidationError(str(error)) from error
    validate_payload(type(value).__name__, payload)
