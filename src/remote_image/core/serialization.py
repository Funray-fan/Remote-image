"""公共契约的 JSON 边界；Path、UTC 时间与嵌套 dataclass 保持统一形状。"""

from __future__ import annotations

import dataclasses
import types
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

SCHEMA_VERSION = "2.0"


def _encode(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: _encode(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("契约时间必须含时区，不自动猜测本地时区")
        return value.isoformat()
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("JSON 对象键必须是字符串")
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_encode(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"不支持的 JSON 值类型: {type(value).__name__}")


def to_payload(value: Any) -> dict[str, Any]:
    """序列化一个契约对象；只在顶层补 schema_version。所有默认/null 字段保留。"""
    result = _encode(value)
    if not isinstance(result, dict):
        raise TypeError("顶层契约必须是 dataclass 或 JSON 对象")
    if result.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise ValueError("新公共契约只能写出 schema_version=2.0")
    return {"schema_version": SCHEMA_VERSION, **result}


def _decode(annotation: Any, value: Any) -> Any:
    if annotation is Any:
        return value
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, types.UnionType):
        for candidate in args:
            try:
                return _decode(candidate, value)
            except (ValueError, TypeError):
                pass
        raise ValueError(f"值不符合联合类型 {annotation}")
    if annotation is type(None):
        if value is not None:
            raise ValueError("预期 null")
        return None
    if origin is Literal:
        if value not in args:
            raise ValueError(f"预期枚举 {args}")
        return value
    if dataclasses.is_dataclass(annotation):
        hints = get_type_hints(annotation)
        names = {field.name for field in dataclasses.fields(annotation)}
        if not isinstance(value, dict) or set(value) != names:
            raise ValueError(f"{annotation.__name__} 字段与契约不一致")
        return annotation(**{name: _decode(hints[name], value[name]) for name in names})
    if annotation is Path:
        if not isinstance(value, str):
            raise ValueError("路径必须是字符串")
        return Path(value)
    if annotation is datetime:
        if not isinstance(value, str):
            raise ValueError("时间必须是 ISO 8601 字符串")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("时间必须含时区")
        return parsed
    if origin in (dict, Mapping):
        return {_decode(args[0], key): _decode(args[1], item) for key, item in value.items()}
    if origin in (list, tuple, Sequence):
        if not isinstance(value, list):
            raise ValueError("预期 JSON 数组")
        if origin is tuple and args and args[-1] is not Ellipsis:
            if len(value) != len(args):
                raise ValueError("定长 tuple 长度不一致")
            return tuple(_decode(kind, item) for kind, item in zip(args, value))
        items = [_decode(args[0], item) for item in value]
        return tuple(items) if origin is tuple else items
    if annotation is float and isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if annotation is int and type(value) is int:
        return value
    if annotation in (str, bool) and isinstance(value, annotation):
        return value
    raise ValueError(f"值不符合 {annotation}")


def from_payload(contract_type: type, payload: dict[str, Any]) -> Any:
    """按显式类型读入 v2，先验证 schema 和跨字段规则；不自动升级 v1。"""
    from remote_image.core.validation import validate_payload

    validate_payload(contract_type.__name__, payload)
    values = dict(payload)
    if "schema_version" not in {field.name for field in dataclasses.fields(contract_type)}:
        values.pop("schema_version")
    return _decode(contract_type, values)
