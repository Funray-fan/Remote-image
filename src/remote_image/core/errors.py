"""Stable C1 pipeline errors for API, CLI, and UI boundaries."""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    INPUT_MISSING = "INPUT_MISSING"
    INPUT_INVALID = "INPUT_INVALID"
    MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
    MODEL_NOT_REGISTERED = "MODEL_NOT_REGISTERED"
    PROCESSING_FAILED = "PROCESSING_FAILED"
    RESULT_INVALID = "RESULT_INVALID"


class PipelineError(RuntimeError):
    """A pipeline error with a stable machine-readable code."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        module: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = ErrorCode(code)
        self.message = message
        self.module = module
        self.details = dict(details or {})
        super().__init__(f"[{self.code.value}] {module}: {message}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "module": self.module,
            "details": self.details,
        }
