"""C1 产物清单：计算文件大小与 SHA-256，并校验现有 v1 Schema。"""
from __future__ import annotations
import hashlib, json, platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _relative_path(value: str | Path, root: Path) -> str:
    path = Path(value).expanduser()
    path = (root / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"产物必须位于项目根目录内：{value}") from exc

def build_manifest(*, event_id: str, stage: str, input_asset_ids: Sequence[str],
                   method: str, artifacts: Mapping[str, str | Path],
                   output_path: str | Path, project_root: str | Path,
                   run_command: str, tests: Sequence[Mapping[str, Any]],
                   warnings: Sequence[str] = (), model_name: str | None = None,
                   model_version: str | None = None,
                   environment: Mapping[str, Any] | None = None,
                   known_limitations: Sequence[str] = (),
                   producer: str = "C1", reviewer: str = "pending",
                   schema_path: str | Path | None = None) -> dict[str, Any]:
    """按 schemas/v1/stage-result-manifest.schema.json 生成清单。"""
    root = Path(project_root).resolve()
    if not event_id.strip() or not method.strip():
        raise ValueError("event_id 和 method 不能为空")
    if stage not in {"stage1", "stage2", "stage3"}:
        raise ValueError("stage 仅支持 stage1/stage2/stage3")
    if not input_asset_ids:
        raise ValueError("v1 Schema 要求至少一个 input_asset_id")
    if not artifacts:
        raise ValueError("v1 Schema 要求至少一个 artifact")
    if not tests:
        raise ValueError("v1 Schema 要求至少一个 test")
    artifact_map, files = {}, []
    for name, value in artifacts.items():
        if not isinstance(name, str) or not name:
            raise ValueError("artifact 名称必须是非空字符串")
        rel = _relative_path(value, root)
        path = (root / rel).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"产物文件不存在：{path}")
        artifact_map[name] = rel
        files.append({"path_or_uri": rel, "size_bytes": path.stat().st_size, "sha256": _sha256(path)})
    manifest = {
        "schema_version": "1.0", "event_id": event_id, "stage": stage,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_asset_ids": list(dict.fromkeys(input_asset_ids)), "method": method,
        "model_name": model_name, "model_version": model_version,
        "artifacts": artifact_map, "files": files, "warnings": list(warnings),
        "run_command": run_command,
        "environment": {"python": platform.python_version(), **dict(environment or {})},
        "tests": [dict(t) for t in tests],
        "known_limitations": list(known_limitations), "producer": producer, "reviewer": reviewer,
    }
    schema_file = Path(schema_path) if schema_path else root / "schemas/v1/stage-result-manifest.schema.json"
    if not schema_file.is_absolute():
        schema_file = root / schema_file
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError('请安装开发依赖：python -m pip install -e ".[dev]"') from exc
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(manifest)
    target = Path(output_path)
    if not target.is_absolute():
        target = root / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
