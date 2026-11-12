"""两期共用阈值分类与全局四邻域清理。输入影像必须已经转换为 dB。"""
from __future__ import annotations

from contextlib import ExitStack
import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window
from scipy import ndimage

from .qa import R2Error

CONNECTIVITY = 4
FOUR_NEIGHBOURS = ndimage.generate_binary_structure(2, 1)


def _finite_number(value, code, message, *, nonnegative=False):
    if isinstance(value, (bool, np.bool_)):
        raise R2Error(code, message, value=str(value))
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise R2Error(code, message, value=str(value)) from exc
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise R2Error(code, message, value=str(value))
    return result


def pixel_area_m2(dataset) -> float:
    """按投影单位和仿射行列式计算面积，不把角度当成米。"""
    if dataset.crs is None or not dataset.crs.is_projected:
        raise R2Error("INVALID_AREA_CRS", "面积计算要求投影坐标系", path=str(dataset.name))
    _, factor = dataset.crs.linear_units_factor
    t = dataset.transform
    area = abs(t.a * t.e - t.b * t.d) * factor * factor
    if not math.isfinite(area) or area <= 0:
        raise R2Error("INVALID_GRID", "像元面积必须为正有限值", path=str(dataset.name))
    return float(area)


def _same_grid(reference, other, *, auxiliary=False):
    code = "AUXILIARY_MASK_MISMATCH" if auxiliary else "GRID_MISMATCH"
    if (other.count != 1 or other.crs != reference.crs
            or other.width != reference.width or other.height != reference.height
            or other.transform != reference.transform):
        raise R2Error(code, "栅格必须为相同 CRS、尺寸和仿射变换的单波段文件",
                      reference=str(reference.name), path=str(other.name))


def _validate_codes(array, allowed, path):
    if not np.isin(array, allowed).all():
        bad = np.unique(array[~np.isin(array, allowed)])[:10]
        raise R2Error("INVALID_MASK", "掩膜包含未约定的编码", path=str(path),
                      expected=list(allowed), actual=[str(v) for v in bad])


def classify_arrays(pre_db, post_db, valid, threshold_db) -> np.ndarray:
    """有效域内识别灾后低于阈值、灾前不低于阈值的像元。"""
    threshold = _finite_number(threshold_db, "INVALID_THRESHOLD", "阈值必须是有限数值")
    pre = np.asarray(pre_db)
    post = np.asarray(post_db)
    validity = np.asarray(valid)
    if pre.ndim != 2 or pre.shape != post.shape or pre.shape != validity.shape:
        raise R2Error("GRID_MISMATCH", "两期数组和有效掩膜必须是同尺寸二维数组")
    if validity.dtype != np.bool_:
        raise R2Error("INVALID_MASK", "内部 valid 必须是布尔数组，True 表示有效")
    effective = validity & np.isfinite(pre) & np.isfinite(post)
    result = np.full(pre.shape, 255, dtype=np.uint8)
    result[effective] = 0
    result[effective & (post < threshold) & (pre >= threshold)] = 1
    return result


def clean_components(mask, min_patch_area_m2, pixel_area_m2):
    """只删除候选类别的小连通域；陆地洞和未知像元保持原样。"""
    values = np.asarray(mask)
    if values.ndim != 2:
        raise R2Error("INVALID_MASK", "分类掩膜必须为二维数组")
    _validate_codes(values, (0, 1, 255), "array")
    minimum = _finite_number(0 if min_patch_area_m2 is None else min_patch_area_m2,
                             "INVALID_PATCH_AREA", "最小斑块面积必须是非负有限数值",
                             nonnegative=True)
    area = _finite_number(pixel_area_m2, "INVALID_GRID", "像元面积必须是正有限数值")
    if area <= 0:
        raise R2Error("INVALID_GRID", "像元面积必须大于 0")
    candidate = values == 1
    labels, component_count = ndimage.label(candidate, structure=FOUR_NEIGHBOURS,
                                            output=np.int32)
    counts = np.bincount(labels.ravel())
    min_pixels = math.ceil(minimum / area)
    keep = counts >= max(1, min_pixels)
    keep[0] = False
    retained = keep[labels]
    result = values.astype(np.uint8, copy=True)
    result[candidate & ~retained] = 0
    before = int(np.count_nonzero(candidate))
    after = int(np.count_nonzero(retained))
    observed = int(np.count_nonzero(values != 255))
    unknown = int(np.count_nonzero(values == 255))
    return result, {
        "connectivity": CONNECTIVITY,
        "pixel_area_m2": area,
        "min_patch_area_m2": minimum,
        "min_patch_pixels": min_pixels,
        "components_before": int(component_count),
        "components_after": int(np.count_nonzero(keep)),
        "raw_candidate_pixels": before,
        "candidate_pixels": after,
        "removed_candidate_pixels": before - after,
        "observed_pixels": observed,
        "valid_pixels": observed,
        "unknown_pixels": unknown,
        "raw_candidate_area_m2": before * area,
        "candidate_area_m2": after * area,
        "observed_area_m2": observed * area,
        "unknown_area_m2": unknown * area,
    }


def _windows(width, height, window_size):
    if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 1:
        raise R2Error("INVALID_WINDOW", "窗口边长必须为正整数")
    for row in range(0, height, window_size):
        for col in range(0, width, window_size):
            yield Window(col, row, min(window_size, width - col), min(window_size, height - row))


def classify_rasters(pre_path, post_path, valid_mask_path, threshold_db,
                     min_patch_area_m2, output_path, permanent_water_mask=None,
                     exclusion_mask=None, *, window_size=1024) -> dict:
    """窗口分类后全区清理，保证跨窗口连通域只按完整面积判定。"""
    threshold = _finite_number(threshold_db, "INVALID_THRESHOLD", "阈值必须是有限数值")
    _finite_number(0 if min_patch_area_m2 is None else min_patch_area_m2,
                   "INVALID_PATCH_AREA", "最小斑块面积必须是非负有限数值", nonnegative=True)
    paths = [Path(pre_path), Path(post_path), Path(valid_mask_path)]
    auxiliaries = {"permanent": permanent_water_mask, "exclusion": exclusion_mask}
    all_inputs = paths + [Path(p) for p in auxiliaries.values() if p is not None]
    output = Path(output_path)
    if output.resolve() in {p.resolve() for p in all_inputs}:
        raise R2Error("OUTPUT_CONFLICT", "输出不能覆盖输入", path=str(output))
    if output.exists():
        raise R2Error("OUTPUT_EXISTS", "输出文件已存在，请使用新的运行目录", path=str(output))
    for path in all_inputs:
        if not path.is_file():
            raise R2Error("MISSING_INPUT", "找不到栅格文件", path=str(path))
    # 提前检查窗口参数，避免创建空的临时文件。
    list(_windows(1, 1, window_size))
    raw_path = output.with_name(output.stem + ".raw.tmp.tif")
    final_temp = output.with_name(output.stem + ".clean.tmp.tif")
    if raw_path.exists() or final_temp.exists():
        raise R2Error("OUTPUT_EXISTS", "同名临时结果已存在，请使用新的运行目录")
    output.parent.mkdir(parents=True, exist_ok=True)
    auxiliary_unknown = 0
    excluded = 0
    permanent = 0
    with ExitStack() as stack:
        pre, post, declared = [stack.enter_context(rasterio.open(p)) for p in paths]
        if pre.count != 1 or pre.crs is None:
            raise R2Error("INVALID_GRID", "灾前分析输入必须为有 CRS 的单波段栅格")
        _same_grid(pre, post)
        _same_grid(pre, declared)
        area = pixel_area_m2(pre)
        aux_readers = {}
        for role, path in auxiliaries.items():
            if path is not None:
                ds = stack.enter_context(rasterio.open(path))
                _same_grid(pre, ds, auxiliary=True)
                aux_readers[role] = ds
        profile = {
            "driver": "GTiff", "height": pre.height, "width": pre.width,
            "count": 1, "dtype": "uint8", "crs": pre.crs,
            "transform": pre.transform, "nodata": 255, "compress": "deflate",
            "tiled": True, "blockxsize": 256, "blockysize": 256,
        }
        with rasterio.open(raw_path, "w", **profile) as target:
            for window in _windows(pre.width, pre.height, window_size):
                a = pre.read(1, window=window)
                b = post.read(1, window=window)
                mask = declared.read(1, window=window)
                _validate_codes(mask, (0, 1), declared.name)
                source_valid = ((pre.read_masks(1, window=window) > 0)
                                & (post.read_masks(1, window=window) > 0)
                                & np.isfinite(a) & np.isfinite(b))
                conflict = (mask == 1) & ~source_valid
                if np.any(conflict):
                    raise R2Error("MASK_SOURCE_CONFLICT", "R1 掩膜把无效观测标为有效",
                                  conflict_pixels=int(np.count_nonzero(conflict)),
                                  row=int(window.row_off), col=int(window.col_off))
                base_valid = (mask == 1) & source_valid
                valid = base_valid.copy()
                aux_values = {}
                unknown = np.zeros(mask.shape, dtype=bool)
                for role, ds in aux_readers.items():
                    aux = ds.read(1, window=window)
                    _validate_codes(aux, (0, 1, 255), ds.name)
                    # 辅助图层的 nodata 元数据也必须得到尊重，包括 nodata=0。
                    unknown |= (aux == 255) | (ds.read_masks(1, window=window) == 0)
                    aux_values[role] = aux
                auxiliary_unknown += int(np.count_nonzero(base_valid & unknown))
                valid &= ~unknown
                if "exclusion" in aux_values:
                    exclusions = aux_values["exclusion"] == 1
                    excluded += int(np.count_nonzero(valid & exclusions))
                    valid &= ~exclusions
                result = classify_arrays(a, b, valid, threshold)
                if "permanent" in aux_values:
                    permanent_pixels = valid & (aux_values["permanent"] == 1)
                    permanent += int(np.count_nonzero(permanent_pixels))
                    result[permanent_pixels] = 0
                target.write(result, 1, window=window)
    with rasterio.open(raw_path) as source:
        raw = source.read(1)
    if not np.any(raw != 255):
        raise R2Error("NO_VALID_DATA", "全部像元均为未知或排除区", raw_path=str(raw_path))
    clean, stats = clean_components(raw, min_patch_area_m2, area)
    with rasterio.open(final_temp, "w", **profile) as target:
        target.write(clean, 1)
        target.set_band_description(1, "new_water_candidate")
        target.update_tags(class_0="not_new_water_candidate", class_1="new_water_candidate",
                           class_255="unknown", connectivity=4, comparison="less_than",
                           water_threshold_db=threshold, method="sar_post_threshold")
    final_temp.replace(output)
    raw_path.unlink()
    stats.update({"status": "pass", "threshold_db": threshold, "output_path": str(output),
                  "window_size": window_size, "auxiliary_unknown_pixels": auxiliary_unknown,
                  "excluded_pixels": excluded, "permanent_water_pixels": permanent})
    return stats
