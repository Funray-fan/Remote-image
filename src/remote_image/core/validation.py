"""JSON Schema 校验与统一校验报告。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "schemas" / "v1"


@dataclass(frozen=True)
class ValidationReport:
    schema_name: str
    errors: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors


@lru_cache(maxsize=None)
def load_schema(schema_name: str) -> dict[str, Any]:
    path = SCHEMA_ROOT / schema_name
    if not path.is_file():
        raise FileNotFoundError(f"未找到 schema: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_json(schema_name: str, instance: Any) -> ValidationReport:
    """按 ``schemas/v1`` 中的 Draft 2020-12 schema 校验实例。"""

    validator = Draft202012Validator(
        load_schema(schema_name),
        format_checker=FormatChecker(),
    )
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    messages = tuple(
        f"{'/'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
        for error in errors
    )
    return ValidationReport(schema_name=schema_name, errors=messages)
