"""R2 的错误、参数与产物检查，不改写共享契约。"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

from remote_image.core.serialization import to_payload
from remote_image.core.validation import validate_contract

METHOD_VERSION = "r2-stage1-0.1.0"


class R2Error(ValueError):
    def __init__(self, code: str, message: str, **details):
        self.code = code
        self.message = message
        self.details = details
        super().__init__(f"{code}: {message}")

    def as_dict(self):
        return {"code": self.code, "message": self.message, "details": self.details}

    to_dict = as_dict


def read_json(path):
    path = Path(path)
    if not path.is_file():
        raise R2Error("MISSING_INPUT", "找不到 JSON 文件", path=str(path))
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _json_default(value):
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, datetime):
        return value.isoformat()
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "tolist"):
        return value.tolist()
    raise TypeError(f"不能序列化 {type(value).__name__}")


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = to_payload(value) if dataclasses.is_dataclass(value) else value
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False, default=_json_default)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(text + "\n", encoding="utf-8")
    temp.replace(path)
    return path


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as src:
        for block in iter(lambda: src.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_options(options):
    validate_contract(options)
    if tuple(options.polarizations) != ("VV",) or options.polarization_rule != "single":
        raise R2Error("UNSUPPORTED_POLARIZATION", "第一版仅支持 VV/single")
    pre = options.pre_water_thresholds_db.get("VV")
    post = options.post_thresholds_db.get("VV")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
           for x in (pre, post)):
        raise R2Error("INVALID_THRESHOLD", "阈值必须是有限数值")
    if pre != post:
        raise R2Error("UNEQUAL_THRESHOLDS", "第一版要求灾前后使用相同阈值", pre=pre, post=post)
    area = options.min_patch_area_m2
    if area is not None and (isinstance(area, bool) or not math.isfinite(area) or area < 0):
        raise R2Error("INVALID_PATCH_AREA", "最小斑块面积必须是非负有限数值")
    return float(post)


def check_flood_artifacts(result):
    validate_contract(result)
    required = {"flood_mask", "flood_polygons", "metadata"}
    missing = required - result.artifacts.keys()
    if missing:
        raise R2Error("MISSING_ARTIFACT", "结果缺少必需产物键", missing=sorted(missing))
    for key, path in result.artifacts.items():
        if not Path(path).is_file():
            raise R2Error("MISSING_ARTIFACT", "产物文件不存在", artifact=key, path=str(path))
    meta = read_json(result.artifacts["metadata"])
    for key in ("event_id", "study_area_id", "method", "method_version"):
        if meta.get(key) != getattr(result.meta, key):
            raise R2Error("ARTIFACT_MISMATCH", "元数据与返回结果不一致", field=key)
    return {"status": "pass", "required_artifacts": sorted(required),
            "sizes_bytes": {k: Path(v).stat().st_size for k, v in result.artifacts.items()}}
