"""将明确声明为 gamma0 线性功率的 R1 输入转换为 R2 分析输入。

这里不生成 sigma0，也不修改公共契约。运行时路径为绝对路径，写出的
prepared_inputs.json 使用该清单所在目录为路径基准。
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
import math

import numpy as np
import rasterio
from rasterio.windows import Window

from remote_image.core.contracts import GridSpec, PreparedInputs, RasterAsset
from remote_image.core.serialization import to_payload
from remote_image.core.validation import validate_contract
from remote_image.modules.flood.qa import R2Error, read_json, sha256_file, write_json

CONVERSION_VERSION = "r2-gamma0-db-1.0"
DB_NODATA = -32768.0
WINDOW_SIZE = 512


def _fail(code: str, message: str, **details: Any) -> None:
    raise R2Error(code, message, **details)


def _windows(ds):
    for row in range(0, ds.height, WINDOW_SIZE):
        for col in range(0, ds.width, WINDOW_SIZE):
            yield Window(col, row, min(WINDOW_SIZE, ds.width - col), min(WINDOW_SIZE, ds.height - row))


def _open(stack: ExitStack, path: Path):
    path = Path(path).resolve()
    if not path.is_file():
        _fail("MISSING_INPUT", "找不到输入文件", path=str(path))
    try:
        return stack.enter_context(rasterio.open(path))
    except rasterio.errors.RasterioError as error:
        _fail("INVALID_INPUT", "无法读取栅格", path=str(path), error=str(error))


def _crs(value):
    try:
        return rasterio.crs.CRS.from_user_input(value)
    except (ValueError, TypeError, rasterio.errors.CRSError) as error:
        _fail("GRID_MISMATCH", "坐标系声明无法解析", value=str(value), error=str(error))


def _grid(ds) -> dict:
    if ds.crs is None or not ds.crs.is_projected:
        _fail("GRID_MISMATCH", "分析输入必须使用以米为单位的投影坐标系", crs=str(ds.crs))
    if not math.isclose(ds.crs.linear_units_factor[1], 1.0, abs_tol=1e-12):
        _fail("GRID_MISMATCH", "分析坐标单位必须为米", units=ds.crs.linear_units)
    values = tuple(ds.transform)[:6]
    if not all(math.isfinite(x) for x in values):
        _fail("GRID_MISMATCH", "仿射变换含非有限数值")
    area = abs(ds.transform.a * ds.transform.e - ds.transform.b * ds.transform.d)
    if area <= 0 or ds.width <= 0 or ds.height <= 0 or ds.count != 1:
        _fail("GRID_MISMATCH", "输入必须是具有有效网格的单波段栅格")
    return {
        "crs": ds.crs.to_string(), "width": ds.width, "height": ds.height,
        "transform": list(values),
        "pixel_size_x_m": math.hypot(ds.transform.a, ds.transform.d),
        "pixel_size_y_m": math.hypot(ds.transform.b, ds.transform.e),
        "pixel_area_m2": area,
    }


def _same_grid(left, right, name: str) -> None:
    _grid(right)
    if left.crs != right.crs or left.shape != right.shape or not np.allclose(
        tuple(left.transform)[:6], tuple(right.transform)[:6], rtol=0, atol=1e-8
    ):
        _fail("GRID_MISMATCH", "两期影像和有效掩膜必须使用相同网格", item=name)


def _source_valid(ds, values, window):
    valid = (ds.read_masks(1, window=window) > 0) & np.isfinite(values)
    if ds.nodata is not None and not np.isnan(ds.nodata):
        valid &= values != ds.nodata
    return valid


def _read_window(pre, post, mask, window):
    a = pre.read(1, window=window, out_dtype="float32")
    b = post.read(1, window=window, out_dtype="float32")
    raw = mask.read(1, window=window)
    if not np.isin(raw, [0, 1]).all():
        _fail("INVALID_MASK", "R1 有效掩膜只允许原始值 0 和 1")
    av, bv = _source_valid(pre, a, window), _source_valid(post, b, window)
    declared = raw == 1
    conflict = declared & ~(av & bv)
    if conflict.any():
        _fail("MASK_SOURCE_CONFLICT", "R1 掩膜将无效源像元标为有效", conflict_pixels=int(conflict.sum()))
    return a, b, av, bv, declared


def _linear_tags(ds) -> None:
    tags = {**ds.tags(), **ds.tags(1)}
    quantity, scale = tags.get("backscatter_quantity"), tags.get("value_scale")
    if quantity is not None and quantity != "gamma0":
        _fail("RADIOMETRY_UNDECLARED", "该私有入口只接受明确的 gamma0 输入", declared=quantity)
    if scale is not None and scale not in ("linear_power", "linear", "power"):
        _fail("RADIOMETRY_UNDECLARED", "不能把 dB 或其他尺度再次转换为 dB", declared=scale)


def _expected(grid: dict, counts: dict, expected: dict | None) -> None:
    if expected is None:
        return
    actual = {**grid, **counts, "pixel_size_m": max(grid["pixel_size_x_m"], grid["pixel_size_y_m"]), "polarization": "VV", "bands": ["VV"], "shape": [grid["height"], grid["width"]]}
    for key, wanted in expected.items():
        if key not in actual:
            _fail("INVALID_INPUT", "未知的输入断言字段", field=key)
        found = actual[key]
        if key == "crs":
            equal = _crs(found) == _crs(wanted)
        elif isinstance(found, (float, int)) and not isinstance(found, bool):
            equal = isinstance(wanted, (float, int)) and math.isclose(found, wanted, rel_tol=0, abs_tol=1e-8)
        elif isinstance(found, list):
            equal = list(wanted) == found
        else:
            equal = found == wanted
        if not equal:
            _fail("INPUT_EXPECTATION_MISMATCH", "实际输入不满足案例断言", field=key, expected=wanted, actual=found)


def inspect_linear_inputs(pre_path, post_path, mask_path, expected=None) -> dict:
    """只读检查显式声明为 gamma0 线性功率的单 VV 影像对。"""
    counts = dict.fromkeys(("total_grid_pixels", "pre_valid_pixels", "post_valid_pixels", "joint_source_valid_pixels", "declared_valid_pixels", "source_mask_restricted_pixels", "nonpositive_power_pixels", "joint_valid_pixels"), 0)
    with ExitStack() as stack:
        pre, post, mask = [_open(stack, p) for p in (pre_path, post_path, mask_path)]
        grid = _grid(pre)
        _same_grid(pre, post, "post_event")
        _same_grid(pre, mask, "valid_mask")
        _linear_tags(pre)
        _linear_tags(post)
        for ds in (pre, post):
            description = ds.descriptions[0]
            if description is not None and description.upper() != "VV":
                _fail("UNSUPPORTED_POLARIZATION", "首版仅支持单波段 VV", description=description)
        counts["total_grid_pixels"] = pre.width * pre.height
        for window in _windows(pre):
            a, b, av, bv, declared = _read_window(pre, post, mask, window)
            source = av & bv
            positive = (a > 0) & (b > 0)
            for key, value in (
                ("pre_valid_pixels", av), ("post_valid_pixels", bv),
                ("joint_source_valid_pixels", source), ("declared_valid_pixels", declared),
                ("source_mask_restricted_pixels", source & ~declared),
                ("nonpositive_power_pixels", source & declared & ~positive),
                ("joint_valid_pixels", source & declared & positive),
            ):
                counts[key] += int(value.sum())
    if counts["joint_valid_pixels"] == 0:
        _fail("NO_VALID_DATA", "没有共同有效且大于零的 gamma0 线性功率像元")
    _expected(grid, counts, expected)
    warnings = []
    if counts["source_mask_restricted_pixels"]:
        warnings.append("R1 掩膜主动限制了部分源有效像元，分析保留这一范围。")
    if counts["nonpositive_power_pixels"]:
        warnings.append("非正线性功率不能取对数，已从分析有效区排除。")
    return {"status": "warning" if warnings else "pass", "grid": grid, "counts": counts,
            "joint_valid_percent_of_rectangular_grid": 100 * counts["joint_valid_pixels"] / counts["total_grid_pixels"],
            "backscatter_quantity": "gamma0", "value_scale": "linear_power", "polarization": "VV", "warnings": warnings}


def _affine(value, name: str) -> tuple:
    if not isinstance(value, (list, tuple)) or len(value) not in (6, 9):
        _fail("INVALID_INPUT", "清单仿射变换必须为六项或标准九项", field=name)
    if len(value) == 9 and list(value[6:]) != [0, 0, 1]:
        _fail("INVALID_INPUT", "九项仿射变换末三项必须为 [0,0,1]", field=name)
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in value):
        _fail("INVALID_INPUT", "清单仿射变换必须是有限数值", field=name)
    return tuple(float(x) for x in value[:6])


def _asset_manifest(raw: dict, ds, name: str) -> datetime:
    required = {"asset_id", "path", "acquired_at", "source", "coordinate_reference_system", "pixel_size_m", "bands", "footprint", "source_type", "is_substitute", "quality_notes"}
    if not isinstance(raw, dict) or required - raw.keys():
        _fail("INVALID_INPUT", "R1 栅格清单缺少元数据字段", field=name, missing=sorted(required - raw.keys()) if isinstance(raw, dict) else sorted(required))
    for key in ("asset_id", "path", "source", "coordinate_reference_system"):
        if not isinstance(raw[key], str) or not raw[key].strip():
            _fail("INVALID_INPUT", "R1 栅格元数据不能为空", field=f"{name}.{key}")
    for key in ("footprint", "quality_notes"):
        if raw[key] is not None and (not isinstance(raw[key], str) or not raw[key].strip()):
            _fail("INVALID_INPUT", "可空元数据必须是字符串或 null", field=f"{name}.{key}")
    if raw["bands"] != ["VV"] or raw["source_type"] != "satellite" or type(raw["is_substitute"]) is not bool:
        _fail("UNSUPPORTED_POLARIZATION", "当前适配器要求卫星单 VV 输入和显式替代标记", field=name)
    try:
        stamp = datetime.fromisoformat(raw["acquired_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("时间无时区")
    except (ValueError, TypeError, AttributeError):
        _fail("INVALID_INPUT", "影像采集时间必须是带时区的 ISO 8601 时间", field=name)
    if _crs(raw["coordinate_reference_system"]) != ds.crs:
        _fail("GRID_MISMATCH", "清单 CRS 与实际 TIFF 不一致", field=name)
    grid = _grid(ds)
    if not isinstance(raw["pixel_size_m"], (int, float)) or not math.isclose(raw["pixel_size_m"], max(grid["pixel_size_x_m"], grid["pixel_size_y_m"]), abs_tol=1e-8):
        _fail("GRID_MISMATCH", "清单像元尺寸与实际 TIFF 不一致", field=name)
    for key, actual in (("width", ds.width), ("height", ds.height), ("count", ds.count)):
        if key in raw and raw[key] != actual:
            _fail("GRID_MISMATCH", "清单尺寸或波段数与实际 TIFF 不一致", field=f"{name}.{key}")
    if "dtype" in raw and raw["dtype"] != ds.dtypes[0]:
        _fail("INVALID_INPUT", "清单像元类型与实际 TIFF 不一致", field=name)
    if "nodata" in raw:
        declared, actual_nodata = raw["nodata"], ds.nodata
        equal = declared is None and actual_nodata is None
        if isinstance(declared, (int, float)) and actual_nodata is not None:
            equal = declared == actual_nodata or (math.isnan(declared) and math.isnan(actual_nodata))
        if not equal:
            _fail("INVALID_INPUT", "清单 NoData 与实际 TIFF 不一致", field=name)
    if "transform" in raw and not np.allclose(_affine(raw["transform"], name), tuple(ds.transform)[:6], rtol=0, atol=1e-8):
        _fail("GRID_MISMATCH", "清单仿射变换与实际 TIFF 不一致", field=name)
    return stamp


def prepare_analysis_inputs(manifest_path, pre_path, post_path, mask_path, output_dir, source_revision=None, expected_hashes=None) -> tuple[PreparedInputs, dict]:
    """显式接纳 gamma0 线性功率；不构造或声称得到 sigma0。"""
    manifest_path = Path(manifest_path).resolve()
    manifest = read_json(manifest_path)
    required = {"pre_event", "post_event", "study_area_id", "grid", "valid_mask"}
    if not isinstance(manifest, dict) or required - manifest.keys() or not isinstance(manifest.get("study_area_id"), str) or not manifest["study_area_id"].strip():
        _fail("INVALID_INPUT", "R1 PreparedInputs 清单不完整")
    if not isinstance(manifest["valid_mask"], str) or not manifest["valid_mask"].strip():
        _fail("INVALID_INPUT", "R1 清单必须明确提供有效掩膜路径")
    source_paths = {"pre_event": Path(pre_path).resolve(), "post_event": Path(post_path).resolve(), "valid_mask": Path(mask_path).resolve()}
    inspected = inspect_linear_inputs(**{f"{key}_path": source_paths[value] for key, value in (("pre", "pre_event"), ("post", "post_event"), ("mask", "valid_mask"))})
    hashes = {name: sha256_file(path) for name, path in source_paths.items()}
    aliases = {"pre": "pre_event", "post": "post_event", "mask": "valid_mask"}
    for key, expected in (expected_hashes or {}).items():
        name = aliases.get(key, key)
        if name not in hashes or not isinstance(expected, str) or hashes[name].lower() != expected.lower():
            _fail("INPUT_HASH_MISMATCH", "输入 SHA-256 不匹配或键名无效", field=key, expected=expected, actual=hashes.get(name))
    output_dir = Path(output_dir).resolve()
    if output_dir == manifest_path.parent or output_dir in (p.parent for p in source_paths.values()):
        _fail("OUTPUT_EXISTS", "派生输入必须写入独立目录，不能覆盖 R1 目录")
    targets = {"pre_event": output_dir / "pre_event_db.tif", "post_event": output_dir / "post_event_db.tif", "valid_mask": output_dir / "valid_mask.tif"}
    for path in (*targets.values(), output_dir / "prepared_inputs.json", output_dir / "input_provenance.json"):
        if path.exists():
            _fail("OUTPUT_EXISTS", "派生输入已存在，请使用新的运行目录", path=str(path))
    with ExitStack() as stack:
        pre, post, mask = [_open(stack, source_paths[key]) for key in ("pre_event", "post_event", "valid_mask")]
        dates = [_asset_manifest(manifest[key], ds, key) for key, ds in (("pre_event", pre), ("post_event", post))]
        if dates[1] < dates[0]:
            _fail("INVALID_INPUT", "灾后影像时间早于灾前影像")
        grid_raw = manifest["grid"]
        keys = {"transform", "width", "height", "pixel_size_x_m", "pixel_size_y_m"}
        if not isinstance(grid_raw, dict) or keys - grid_raw.keys():
            _fail("INVALID_INPUT", "R1 GridSpec 字段不完整")
        actual = inspected["grid"]
        if not np.allclose(_affine(grid_raw["transform"], "grid"), actual["transform"], rtol=0, atol=1e-8):
            _fail("GRID_MISMATCH", "R1 GridSpec 变换与实际 TIFF 不一致")
        for key in keys - {"transform"}:
            if not isinstance(grid_raw[key], (int, float)) or not math.isclose(grid_raw[key], actual[key], rel_tol=0, abs_tol=1e-8):
                _fail("GRID_MISMATCH", "R1 GridSpec 与实际 TIFF 不一致", field=key)
        output_dir.mkdir(parents=True, exist_ok=True)
        profile = {"driver": "GTiff", "height": pre.height, "width": pre.width, "count": 1, "crs": pre.crs, "transform": pre.transform, "tiled": True, "blockxsize": 256, "blockysize": 256, "compress": "deflate"}
        aout = stack.enter_context(rasterio.open(targets["pre_event"], "w", **profile, dtype="float32", nodata=DB_NODATA))
        bout = stack.enter_context(rasterio.open(targets["post_event"], "w", **profile, dtype="float32", nodata=DB_NODATA))
        mout = stack.enter_context(rasterio.open(targets["valid_mask"], "w", **profile, dtype="uint8", nodata=0))
        for window in _windows(pre):
            a, b, av, bv, declared = _read_window(pre, post, mask, window)
            valid = av & bv & declared & (a > 0) & (b > 0)
            for values, dst in ((a, aout), (b, bout)):
                db = np.full(values.shape, DB_NODATA, dtype="float32")
                db[valid] = 10.0 * np.log10(values[valid])
                dst.write(db, 1, window=window)
            mout.write(valid.astype("uint8"), 1, window=window)
        for key, dst in (("pre_event", aout), ("post_event", bout)):
            dst.set_band_description(1, "VV")
            dst.update_tags(backscatter_quantity="gamma0", value_scale="db", polarization="VV", source_sha256=hashes[key], conversion_version=CONVERSION_VERSION)
        mout.set_band_description(1, "valid_pre_post_positive_gamma0")
    assets = []
    for key, stamp in zip(("pre_event", "post_event"), dates):
        raw = manifest[key]
        assets.append(RasterAsset(asset_id=raw["asset_id"] + "_r2_gamma0_db", path=targets[key], acquired_at=stamp, source=raw["source"], coordinate_reference_system=actual["crs"], pixel_size_m=max(actual["pixel_size_x_m"], actual["pixel_size_y_m"]), bands=("VV",), footprint=None, source_type="satellite", is_substitute=raw["is_substitute"], quality_notes="R2 gamma0 dB 派生输入；不是 sigma0。原始来源见 input_provenance.json。"))
    inputs = PreparedInputs(assets[0], assets[1], manifest["study_area_id"], GridSpec(tuple(actual["transform"]), actual["width"], actual["height"], actual["pixel_size_x_m"], actual["pixel_size_y_m"]), targets["valid_mask"])
    validate_contract(inputs)
    analysis_check = check_analysis_inputs(inputs)
    provenance = {"r2_input_provenance_version": "1.0", "source_revision": source_revision, "manifest_path": str(manifest_path), "manifest_sha256": sha256_file(manifest_path), "declared_input_radiometry": {"backscatter_quantity": "gamma0", "value_scale": "linear_power", "declaration_source": "explicit prepare_analysis_inputs entry"}, "output_radiometry": {"backscatter_quantity": "gamma0", "value_scale": "db"}, "conversion_version": CONVERSION_VERSION, "source_files": {key: {"path": str(path), "sha256": hashes[key], "manifest_path": manifest.get(key, {}).get("path") if isinstance(manifest.get(key), dict) else manifest.get(key)} for key, path in source_paths.items()}, "asset_id_mapping": {manifest[key]["asset_id"]: asset.asset_id for key, asset in zip(("pre_event", "post_event"), assets)}, "linear_input_check": inspected, "analysis_input_check": analysis_check, "prepared_inputs_path_base": ".", "warnings": inspected["warnings"] + ["本地 gamma0 技术基线；当前固定 sigma0/db 的团队规格需另行确认。"]}
    portable = replace(inputs, pre_event=replace(inputs.pre_event, path=Path(targets["pre_event"].name)), post_event=replace(inputs.post_event, path=Path(targets["post_event"].name)), valid_mask=Path(targets["valid_mask"].name))
    write_json(output_dir / "prepared_inputs.json", to_payload(portable))
    write_json(output_dir / "input_provenance.json", provenance)
    return inputs, provenance


def check_analysis_inputs(inputs: PreparedInputs) -> dict:
    """检查真实派生文件及标签，拒绝未声明单位或重复转换的输入。"""
    validate_contract(inputs)
    if inputs.pre_event is None or inputs.valid_mask is None:
        _fail("MISSING_INPUT", "洪水基线必须提供灾前影像和共同有效掩膜")
    for asset in (inputs.pre_event, inputs.post_event):
        if asset.bands != ("VV",):
            _fail("UNSUPPORTED_POLARIZATION", "首版仅支持单 VV 分析输入")
    valid_count = 0
    with ExitStack() as stack:
        pre, post, mask = [_open(stack, p) for p in (inputs.pre_event.path, inputs.post_event.path, inputs.valid_mask)]
        grid = _grid(pre)
        _same_grid(pre, post, "post_event")
        _same_grid(pre, mask, "valid_mask")
        for ds, asset in ((pre, inputs.pre_event), (post, inputs.post_event)):
            tags = {**ds.tags(), **ds.tags(1)}
            if any(tags.get(key) != value for key, value in (("backscatter_quantity", "gamma0"), ("value_scale", "db"), ("polarization", "VV"))):
                _fail("RADIOMETRY_UNDECLARED", "分析 TIFF 必须显式标记 gamma0/db/VV", path=str(asset.path))
            if ds.dtypes[0] != "float32" or ds.nodata != DB_NODATA:
                _fail("INVALID_INPUT", "派生分析输入必须为 float32 并使用约定 NoData", path=str(asset.path))
            if _crs(asset.coordinate_reference_system) != ds.crs:
                _fail("GRID_MISMATCH", "RasterAsset CRS 与实际 TIFF 不一致")
        if inputs.grid.width != grid["width"] or inputs.grid.height != grid["height"] or not np.allclose(inputs.grid.transform, grid["transform"], rtol=0, atol=1e-8) or not math.isclose(inputs.grid.pixel_size_x_m, grid["pixel_size_x_m"], abs_tol=1e-8) or not math.isclose(inputs.grid.pixel_size_y_m, grid["pixel_size_y_m"], abs_tol=1e-8):
            _fail("GRID_MISMATCH", "PreparedInputs 网格与实际 TIFF 不一致")
        for window in _windows(pre):
            _, _, av, bv, declared = _read_window(pre, post, mask, window)
            if not np.array_equal(av & bv, declared):
                _fail("MASK_SOURCE_CONFLICT", "派生分析影像有效区与共同掩膜不一致")
            valid_count += int(declared.sum())
    if valid_count == 0:
        _fail("NO_VALID_DATA", "派生分析输入没有共同有效像元")
    return {"status": "pass", "grid": grid, "counts": {"total_grid_pixels": grid["width"] * grid["height"], "joint_valid_pixels": valid_count}, "backscatter_quantity": "gamma0", "value_scale": "db", "polarization": "VV", "warnings": []}
