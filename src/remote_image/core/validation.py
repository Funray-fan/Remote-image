"""C1 阶段一结果校验；复用现有公共对象和 schemas，不定义新 DTO。"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Mapping


def _to_mapping(result: Any) -> dict[str, Any]:
    if is_dataclass(result):
        return asdict(result)
    if isinstance(result, Mapping):
        return dict(result)
    raise TypeError("result 必须是 dict/mapping 或仓库公共 dataclass 结果对象")


def validate_result(
    result: Any,
    *,
    required_artifacts: tuple[str, ...] = (),
    check_files: bool = True,
) -> dict[str, Any]:
    """检查结果的 artifacts、ResultMeta 必需字段和产物文件存在性。

    返回统一校验报告：status、checks、errors。若业务模块结果尚未定义
    专用 schema，先执行本层通用检查；模块 schema 由模块负责人提交，
    C1 再通过 validate_against_schema 集成。
    """
    data = _to_mapping(result)
    errors: list[dict[str, str]] = []
    artifacts = data.get("artifacts")

    if not isinstance(artifacts, Mapping):
        errors.append({
            "path": "artifacts",
            "message": "必须提供 artifacts 字典，键为固定产物名，值为文件路径",
        })
        artifacts = {}

    for key in required_artifacts:
        if key not in artifacts:
            errors.append({
                "path": f"artifacts.{key}",
                "message": "缺少必需产物",
            })

    for key, value in artifacts.items():
        if not isinstance(value, (str, Path)):
            errors.append({
                "path": f"artifacts.{key}",
                "message": "产物路径必须是字符串或 pathlib.Path",
            })
            continue
        raw_path = str(value)
        if check_files and not raw_path.startswith(("http://", "https://", "s3://")):
            if not Path(value).is_file():
                errors.append({
                    "path": f"artifacts.{key}",
                    "message": f"产物文件不存在：{raw_path}",
                })

    meta = data.get("meta")
    if meta is None:
        errors.append({"path": "meta", "message": "缺少 ResultMeta 元数据"})
    else:
        meta_data = asdict(meta) if is_dataclass(meta) else meta
        if not isinstance(meta_data, Mapping):
            errors.append({"path": "meta", "message": "meta 必须是对象或 ResultMeta"})
        else:
            required_meta = (
                "schema_version", "event_id", "study_area_id",
                "input_asset_ids", "method", "method_version",
            )
            for field_name in required_meta:
                if field_name not in meta_data or meta_data[field_name] is None:
                    errors.append({
                        "path": f"meta.{field_name}",
                        "message": "缺少必需元数据字段",
                    })

    checks = [
        {
            "name": "artifacts_and_metadata",
            "status": "fail" if errors else "pass",
        }
    ]
    return {
        "status": "fail" if errors else "pass",
        "checks": checks,
        "errors": errors,
    }


def validate_against_schema(
    payload: dict[str, Any],
    schema_path: str | Path,
) -> dict[str, Any]:
    """调用仓库已有 JSON Schema；不会新建或修改共享 schema。"""
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError(
            "Schema 校验需要开发依赖，请执行：python -m pip install -e \".[dev]\""
        ) from exc

    path = Path(schema_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Schema 文件不存在：{path}")

    import json
    schema = json.loads(path.read_text(encoding="utf-8"))
    errors = sorted(
        jsonschema.Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: list(error.path),
    )
    return {
        "status": "fail" if errors else "pass",
        "errors": [
            {
                "path": ".".join(str(part) for part in error.absolute_path) or "$",
                "message": error.message,
            }
            for error in errors
        ],
    }
