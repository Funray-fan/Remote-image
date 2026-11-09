"""C1 阶段一工作流：按配置调用 R1 -> R2 -> R3，并写出运行摘要。"""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from remote_image.core.config import load_config
from remote_image.core.contracts import ResultMeta
from remote_image.core.metadata import write_metadata
from remote_image.core.manifest import build_manifest

LOGGER = logging.getLogger("remote_image.c1.stage1")


def _resolve_callable(target: str):
    module_name, function_name = target.split(":", 1)
    if not module_name.startswith("remote_image."):
        raise ValueError(f"只允许调用 remote_image 包内模块：{module_name}")
    module = importlib.import_module(module_name)
    function = getattr(module, function_name, None)
    if not callable(function):
        raise AttributeError(f"模块函数不存在或不可调用：{target}")
    return function


def _resolve_step_refs(value: Any, outputs: dict[str, Any]) -> Any:
    """支持 '$step.name' 和 '$step.name.field' 引用前序步骤输出。"""
    if isinstance(value, str) and value.startswith("$step."):
        parts = value[len("$step."):].split(".")
        if parts[0] not in outputs:
            raise KeyError(f"引用了尚未产生的步骤输出：{value}")
        current = outputs[parts[0]]
        for part in parts[1:]:
            if isinstance(current, Mapping):
                current = current[part]
            else:
                current = getattr(current, part)
        return current
    if isinstance(value, dict):
        return {key: _resolve_step_refs(item, outputs) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_step_refs(item, outputs) for item in value]
    return value


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def run_pipeline(config: dict[str, Any]) -> dict[str, Any]:
    """运行配置中的模块步骤，并在 outputs/<event_id>/stage1/ 写 summary.json。

    每个 step: name、callable='remote_image.xxx:function'、kwargs、enabled。
    通过 '$step.<name>' 可把前序模块返回值传给后续模块。
    """
    started_at = datetime.now(timezone.utc)
    timer = time.perf_counter()
    project_root = Path(config.get("_project_root", Path.cwd())).resolve()
    output_dir = Path(config["output_dir"]).resolve() / config["event_id"] / "stage1"
    output_dir.mkdir(parents=True, exist_ok=True)

    step_outputs: dict[str, Any] = {}
    step_records: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: list[dict[str, str]] = []
    status = "pass"

    for step in config.get("steps", []):
        step_name = step["name"]
        if step.get("enabled", True) is False:
            step_records.append({
                "name": step_name,
                "status": "skipped",
                "duration_seconds": 0.0,
            })
            continue

        step_timer = time.perf_counter()
        try:
            function = _resolve_callable(step["callable"])
            kwargs = _resolve_step_refs(step.get("kwargs", {}), step_outputs)
            output = function(**kwargs)
            step_outputs[step_name] = output
            step_records.append({
                "name": step_name,
                "status": "pass",
                "duration_seconds": round(time.perf_counter() - step_timer, 6),
            })
            LOGGER.info("步骤完成：%s", step_name)
        except Exception as exc:
            status = "fail"
            errors.append({
                "step": step_name,
                "type": type(exc).__name__,
                "message": str(exc),
            })
            step_records.append({
                "name": step_name,
                "status": "fail",
                "duration_seconds": round(time.perf_counter() - step_timer, 6),
                "message": str(exc),
            })
            LOGGER.exception("阶段一工作流步骤失败：%s", step_name)
            break

    if not config.get("steps"):
        status = "warning"
        warnings.append(
            "steps 为空：仅验证 C1 工作流入口，未调用 R1/R2/R3 业务模块。"
        )
    elif status == "pass" and not any(
        item["status"] == "pass" for item in step_records
    ):
        status = "warning"
        warnings.append("没有实际执行的业务步骤（所有步骤均被禁用）。")

    finished_at = datetime.now(timezone.utc)
    try:
        output_relative = output_dir.relative_to(project_root).as_posix()
    except ValueError:
        output_relative = output_dir.name
        warnings.append("输出目录位于项目根目录之外，摘要仅记录目录名。")

    summary = {
        "schema_version": "1.0",
        "event_id": config["event_id"],
        "study_area_id": config["study_area_id"],
        "stage": "stage1",
        "status": status,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round(time.perf_counter() - timer, 6),
        "output_dir": output_relative,
        "steps": step_records,
        "warnings": warnings,
        "errors": errors,
        "step_outputs": _jsonable(step_outputs),
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    LOGGER.info("阶段一结束：status=%s，summary=%s", status, summary_path)
    # 仅在有真实输入资产 ID 时写 metadata/manifest，不伪造业务输入。
    input_asset_ids = list(config.get("input_asset_ids", []))
    artifacts: dict[str, str] = {}
    methods, model_name, model_version = [], None, None
    for step_name, output in step_outputs.items():
        meta = getattr(output, "meta", None)
        if meta is not None:
            input_asset_ids.extend(list(getattr(meta, "input_asset_ids", ()) or ()))
            if getattr(meta, "method", None):
                methods.append(str(meta.method))
        output_artifacts = getattr(output, "artifacts", None)
        if isinstance(output_artifacts, Mapping):
            for artifact_name, artifact_path in output_artifacts.items():
                key = f"{step_name}_{artifact_name}".lower()
                key = "".join(c if c.isalnum() or c == "_" else "_" for c in key)
                artifacts[key] = str(artifact_path)
        if getattr(output, "model_name", None):
            model_name = str(output.model_name)
            model_version = str(getattr(output, "model_version", "")) or None

    if input_asset_ids:
        meta_record = ResultMeta(
            schema_version="1.0", event_id=config["event_id"],
            study_area_id=config["study_area_id"],
            input_asset_ids=tuple(dict.fromkeys(input_asset_ids)),
            method=";".join(dict.fromkeys(methods)) or "stage1_pipeline",
            method_version="1.0",
            parameters={"stage": "stage1", "steps": [x["name"] for x in step_records]},
            created_at=finished_at, warnings=tuple(warnings),
        )
        metadata_path = output_dir / "metadata.json"
        write_metadata(meta_record, metadata_path)
        artifacts["metadata"] = metadata_path.relative_to(project_root).as_posix()
        try:
            manifest_path = output_dir / "stage-result-manifest.json"
            build_manifest(
                event_id=config["event_id"], stage="stage1",
                input_asset_ids=list(dict.fromkeys(input_asset_ids)),
                method=meta_record.method, artifacts=artifacts,
                output_path=manifest_path, project_root=project_root,
                run_command=config.get(
                    "run_command",
                    "python -m remote_image.workflows.stage1 --config configs/c1-stage1.example.json",
                ),
                tests=config.get("manifest_tests", [
                    {"name": "c1_stage1_pipeline", "status": "not_run",
                     "details": "请由 CI/验收流程回填真实测试状态"}
                ]),
                warnings=warnings, model_name=model_name, model_version=model_version,
                known_limitations=config.get("known_limitations", []),
                producer=config.get("producer", "C1"),
                reviewer=config.get("reviewer", "pending"),
            )
            summary["metadata_path"] = metadata_path.relative_to(project_root).as_posix()
            summary["manifest_path"] = manifest_path.relative_to(project_root).as_posix()
        except Exception as exc:
            summary["warnings"].append(f"manifest 未生成：{type(exc).__name__}: {exc}")
            LOGGER.warning("manifest 未生成：%s", exc)
    else:
        summary["warnings"].append(
            "未提供 input_asset_ids，跳过 metadata/manifest；真实运行必须提供输入资产 ID。"
        )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remote Image C1 阶段一工作流")
    parser.add_argument("--config", required=True, help="阶段一 JSON/YAML 配置路径")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    config = load_config(args.config)
    result = run_pipeline(config)
    print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2))
    return 1 if result["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
