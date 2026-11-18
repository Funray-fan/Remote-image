"""Display the model identity and C1-validated package evidence for a result."""

from pathlib import Path

from remote_image.core.model_manifest import load_model_manifest
from remote_image.core.serialization import to_payload
from .stage1 import VisualizationInputError
from .stage2 import DamageMapResult, _local_file


def load_model_evidence(path: Path, result: DamageMapResult, *, allowed_root: Path) -> dict:
    root = allowed_root.resolve()
    path = _local_file(path, root, root)
    manifest = load_model_manifest(path, project_root=root)
    if (manifest.model_name, manifest.model_version) != (result.model_name, result.model_version):
        raise VisualizationInputError("模型包名称/版本与当前损毁结果不一致")
    if manifest.task != "building_damage":
        raise VisualizationInputError("当前页面需要 building_damage 模型包")
    classes = set(manifest.class_map.values())
    if any(feature["properties"]["damage_class"] not in classes for feature in result.features.values()):
        raise VisualizationInputError("损毁结果包含该模型包未声明的类别")
    return to_payload(manifest)
