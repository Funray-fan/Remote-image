"""C1 公共错误类型与稳定错误码。"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    INPUT_MISSING = "INPUT_MISSING"
    INPUT_INVALID = "INPUT_INVALID"
    CRS_MISMATCH = "CRS_MISMATCH"
    NO_VALID_PIXELS = "NO_VALID_PIXELS"
    MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
    PROCESSING_FAILED = "PROCESSING_FAILED"


class PipelineError(RuntimeError):
    """可被 CLI、API 或界面统一映射的流水线错误。"""

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
