"""C1 阶段一配置读取与校验。配置文件中的路径保持项目相对形式。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """配置缺失、格式错误或字段不符合约定。"""


def _read_config_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(
                f"JSON 格式错误（第 {exc.lineno} 行，第 {exc.colno} 列）：{exc.msg}"
            ) from exc
    elif suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:
            raise ConfigError(
                "读取 YAML 配置需要 PyYAML，请执行：python -m pip install PyYAML"
            ) from exc
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ConfigError(f"YAML 格式错误：{exc}") from exc
    else:
        raise ConfigError("配置文件格式仅支持 .json、.yaml、.yml")

    if not isinstance(data, dict):
        raise ConfigError("配置文件最外层必须是对象（mapping）")
    return data


def load_config(path: str | Path) -> dict[str, Any]:
    """读取阶段一配置并检查必需字段、步骤定义和输出路径。

    必需字段：event_id、study_area_id、output_dir、steps。
    返回值附带仅供运行时使用的 _project_root/_config_path；
    不会把本机绝对路径写回配置文件或运行摘要。
    """
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise ConfigError(f"配置文件不存在：{config_path}")

    data = _read_config_file(config_path)
    required = ("event_id", "study_area_id", "output_dir", "steps")
    missing = [key for key in required if key not in data]
    if missing:
        raise ConfigError("配置缺少必需字段：" + ", ".join(missing))

    for key in ("event_id", "study_area_id", "output_dir"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise ConfigError(f"配置字段 {key} 必须是非空字符串")

    steps = data["steps"]
    if not isinstance(steps, list):
        raise ConfigError("配置字段 steps 必须是数组")

    seen: set[str] = set()
    for index, step in enumerate(steps):
        prefix = f"steps[{index}]"
        if not isinstance(step, dict):
            raise ConfigError(f"{prefix} 必须是对象")
        name = step.get("name")
        target = step.get("callable")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{prefix}.name 必须是非空字符串")
        if name in seen:
            raise ConfigError(f"步骤名称重复：{name}")
        seen.add(name)
        if not isinstance(target, str) or ":" not in target:
            raise ConfigError(
                f"{prefix}.callable 必须采用 module:function 格式"
            )
        module_name, function_name = target.split(":", 1)
        if not module_name.startswith("remote_image.") or not function_name:
            raise ConfigError(
                f"{prefix}.callable 只能指向 remote_image 包内的函数"
            )
        if not isinstance(step.get("kwargs", {}), dict):
            raise ConfigError(f"{prefix}.kwargs 必须是对象")
        if "enabled" in step and not isinstance(step["enabled"], bool):
            raise ConfigError(f"{prefix}.enabled 必须是布尔值")

    project_root = (
        config_path.parent.parent
        if config_path.parent.name == "configs"
        else config_path.parent
    ).resolve()
    output_path = Path(data["output_dir"]).expanduser()
    if not output_path.is_absolute():
        output_path = (project_root / output_path).resolve()

    data["_project_root"] = project_root
    data["_config_path"] = config_path
    data["output_dir"] = output_path
    return data
