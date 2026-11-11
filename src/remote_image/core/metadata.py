"""C1 元数据写入：使用仓库公共 ResultMeta。"""
from __future__ import annotations
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from remote_image.core.contracts import ResultMeta

def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    return value

def write_metadata(metadata: ResultMeta | Mapping[str, Any], output_path: str | Path) -> Path:
    """将 ResultMeta 或字段映射写入 UTF-8 JSON。"""
    if isinstance(metadata, ResultMeta):
        from remote_image.core.validation import validate_contract
        validate_contract(metadata)
        payload = _jsonable(metadata)
    elif isinstance(metadata, Mapping):
        payload = _jsonable(metadata)
    else:
        raise TypeError("metadata 必须是 contracts.ResultMeta 或 Mapping")
    required = ("schema_version", "event_id", "study_area_id", "input_asset_ids", "method", "method_version")
    missing = [k for k in required if k not in payload or payload[k] is None]
    if missing:
        raise ValueError("元数据缺少必需字段：" + ", ".join(missing))
    payload["input_asset_ids"] = list(payload["input_asset_ids"])
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
