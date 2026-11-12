"""候选参数比较；无参考标签时不计算或编造识别精度。"""
from __future__ import annotations
import csv
from pathlib import Path
import numpy as np
import rasterio
from scipy import ndimage

from remote_image.core.contracts import ThresholdReport, CheckItem
from remote_image.core.serialization import to_payload
from remote_image.core.validation import validate_contract
from .input_io import check_analysis_inputs
from .classification import classify_rasters
from .qa import R2Error, validate_options, write_json, sha256_file


def confusion_metrics(predicted, reference, valid):
    p, r = predicted[valid], reference[valid]
    tp, fp = int(((p == 1) & (r == 1)).sum()), int(((p == 1) & (r == 0)).sum())
    fn, tn = int(((p == 0) & (r == 1)).sum()), int(((p == 0) & (r == 0)).sum())
    ratio = lambda a, b: a / b if b else None
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "evaluated_pixels": int(valid.sum()),
            "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn),
            "f1": ratio(2 * tp, 2 * tp + fp + fn), "iou": ratio(tp, tp + fp + fn)}


def evaluate_candidates(inputs, candidates, reference, output_dir, development_mask=None):
    """私有入口可指定统计区域；分类和清理始终在完整网格执行。"""
    candidates = tuple(candidates)
    if not candidates:
        raise R2Error("EMPTY_CANDIDATES", "至少需要一个明确的候选配置")
    check_analysis_inputs(inputs)
    for item in candidates:
        validate_options(item)
    def auxiliary_signature(option):
        signature = []
        for value in (option.permanent_water_mask, option.exclusion_mask):
            if value is not None and not Path(value).is_file():
                raise R2Error("MISSING_INPUT", "辅助掩膜不存在", path=str(value))
            signature.append(sha256_file(value) if value is not None else None)
        return tuple(signature)
    if len({auxiliary_signature(item) for item in candidates}) != 1:
        raise R2Error("INCOMPARABLE_CANDIDATES", "候选必须采用内容一致的辅助掩膜")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    with rasterio.open(inputs.post_event.path) as src:
        shape, transform, crs = src.shape, src.transform, src.crs
    region = np.ones(shape, dtype=bool) if development_mask is None else np.asarray(development_mask)
    if region.dtype != bool or region.shape != shape or not region.any():
        raise R2Error("INVALID_DEVELOPMENT_MASK", "开发区必须是同网格的非空布尔掩膜")
    ref = None
    if reference is not None:
        with rasterio.open(reference) as src:
            if src.shape != shape or src.crs != crs or not src.transform.almost_equals(transform):
                raise R2Error("REFERENCE_GRID_MISMATCH", "参考标签必须与分析网格一致")
            tags = src.tags()
            if tags.get("target") != "new_flood":
                raise R2Error("REFERENCE_TARGET_MISMATCH", "参考标签必须声明 target=new_flood")
            for key, asset in (("pre_event_date", inputs.pre_event), ("post_event_date", inputs.post_event)):
                if asset.acquired_at is None or tags.get(key) != asset.acquired_at.date().isoformat():
                    raise R2Error("REFERENCE_DATE_MISMATCH", "参考标签时段不匹配", field=key)
            ref = src.read(1)
            if not np.isin(ref, [0, 1, 255]).all():
                raise R2Error("INVALID_REFERENCE", "参考标签只允许 0、1、255")
            ref = np.where(src.read_masks(1) > 0, ref, 255).astype("uint8")
    rows, paths = [], []
    fixed_usable = None
    pixel_area = abs(transform.a * transform.e - transform.b * transform.d)
    for i, options in enumerate(candidates):
        path = out / f"candidate_{i:02d}.tif"
        classify_rasters(inputs.pre_event.path, inputs.post_event.path, inputs.valid_mask,
                         validate_options(options), options.min_patch_area_m2 or 0, path,
                         permanent_water_mask=options.permanent_water_mask,
                         exclusion_mask=options.exclusion_mask)
        with rasterio.open(path) as src:
            predicted = src.read(1)
        usable = region & (predicted != 255)
        if fixed_usable is None:
            fixed_usable = usable.copy()
        elif not np.array_equal(fixed_usable, usable):
            raise R2Error("INCOMPARABLE_CANDIDATES", "候选评价有效范围不一致")
        labels, _ = ndimage.label(predicted == 1, structure=ndimage.generate_binary_structure(2, 1))
        components = np.unique(labels[region & (predicted == 1)])
        row = {"candidate_index": i, "threshold_db": options.post_thresholds_db["VV"],
               "min_patch_area_m2": options.min_patch_area_m2 or 0,
               "observed_pixels": int(usable.sum()),
               "candidate_pixels": int(((predicted == 1) & region).sum()),
               "candidate_area_m2": float(((predicted == 1) & region).sum() * pixel_area),
               "components_intersecting_development": int(len(components)),
               "precision": None, "recall": None, "f1": None, "iou": None}
        if not usable.any():
            raise R2Error("NO_VALID_DEVELOPMENT_DATA", "开发区没有可分类像元")
        if ref is not None:
            comparison = usable & (ref != 255)
            if not comparison.any():
                raise R2Error("NO_VALID_REFERENCE", "参考与开发区没有共同有效标签")
            row.update(confusion_metrics(predicted, ref, comparison))
        rows.append(row)
        paths.append(path)
    if ref is None:
        selected = 0
        reason = "无独立参考标签；按配置候选顺序采用第 0 项作为试运行参数，不声称最优。"
        warnings = ("精度未验证；候选面积和碎斑变化仅用于开发区诊断。",)
    else:
        eligible = [i for i, row in enumerate(rows) if row["f1"] is not None]
        selected = max(eligible, key=lambda i: rows[i]["f1"]) if eligible else 0
        reason = ("指定评价范围内 F1 最大值；并列按候选顺序。" if eligible
                  else "指定评价范围内所有候选 F1 无定义，按顺序采用第 0 项试运行。")
        warnings = ("这份报告是开发区评估，不是独立测试区精度。",)
    csv_path = out / "threshold_candidates.csv"
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    report = ThresholdReport(status="warning", checks=(CheckItem("candidate_execution", "pass", len(candidates), len(rows), "全部候选执行完成"),),
        metrics={"candidates": rows, "selected_index": selected,
                 "precision": rows[selected]["precision"], "recall": rows[selected]["recall"],
                 "f1": rows[selected]["f1"], "iou": rows[selected]["iou"],
                 "development_pixels": int(region.sum()),
                 "evaluation_scope": "explicit_development_mask" if development_mask is not None else "entire_supplied_grid",
                 "heldout_isolation_verified_by_function": False},
        warnings=warnings, artifacts={"comparison_table": csv_path, **{f"candidate_{i}": p for i,p in enumerate(paths)}},
        candidate_options=candidates, selected_options=candidates[selected],
        reference_available=ref is not None, selection_reason=reason)
    validate_contract(report)
    write_json(out / "threshold_report.json", report)
    write_json(out / "selected_options.json", report.selected_options)
    return report


def evaluate_flood_thresholds(inputs, candidates, reference, output_dir):
    """公共接口默认评估传入完整范围；区域约束由私有案例入口显式指定。"""
    return evaluate_candidates(inputs, candidates, reference, output_dir)
