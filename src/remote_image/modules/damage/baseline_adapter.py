
"""C2 Stage 1 空结果基线适配器。

本适配器仅用于验证模块接口和工作流连接。
不读取真实影像，不运行损毁识别模型，不生成虚构损毁记录。
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from remote_image.core.contracts import (
    DamageRequest,
    DamageResult,
    InferenceOptions,
    ResultMeta,
)


@dataclass
class EmptyBaselineDamageAdapter:
    """生成符合当前 Python 契约的空结果基线。"""

    output_root: Path = Path("outputs")
    name: str = "baseline_damage_model"
    version: str = "0.1.0"

    def predict(
        self,
        request: DamageRequest,
        options: InferenceOptions | None = None,
    ) -> DamageResult:

        # 1. 生成安全的事件目录名称，避免事件编号包含路径分隔符。
        safe_event_id = re.sub(
            r"[^A-Za-z0-9._-]+", "_", request.event_id
        ).strip("._")

        if not safe_event_id:
            raise ValueError("event_id cannot produce a valid output directory")

        # 2. 按项目约定保存到 outputs/<event_id>/stage1。
        output_dir = (
            Path(self.output_root)
            / safe_event_id
            / "stage1"
            / "damage"
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        damage_vector_path = output_dir / "damage_vector.geojson"
        tile_index_path = output_dir / "tile_index.geojson"
        metadata_path = output_dir / "metadata.json"

        # 3. 生成空的 GeoJSON FeatureCollection。
        # 不添加任何建筑物损毁记录或虚构切片记录。
        empty_geojson = {
            "type": "FeatureCollection",
            "features": [],
        }

        damage_vector_path.write_text(
            json.dumps(empty_geojson, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        tile_index_path.write_text(
            json.dumps(empty_geojson, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 4. 记录本次请求使用的输入影像编号。
        input_asset_ids = tuple(
            dict.fromkeys(
                asset.asset_id
                for asset in (request.pre_event, request.post_event)
                if asset is not None
            )
        )

        parameters = {
            "baseline_mode": "empty",
            "fixture_only": True,
            "inference_options": (
                asdict(options) if options is not None else {}
            ),
        }

        warnings = (
            "Stage 1 empty baseline only.",
            "No real image inference was performed.",
            "No actual building damage labels were generated.",
        )

        created_at = datetime.now(timezone.utc)

        # 5. 构造 Python 公共接口要求的结果元信息。
        meta = ResultMeta(
            schema_version="1.0",
            event_id=request.event_id,
            study_area_id=request.study_area.identifier,
            input_asset_ids=input_asset_ids,
            method=request.task,
            method_version=self.version,
            parameters=parameters,
            created_at=created_at,
            warnings=warnings,
        )

        # 6. 同步写出 metadata.json，便于后续模块读取。
        metadata = {
            "schema_version": meta.schema_version,
            "event_id": meta.event_id,
            "study_area_id": meta.study_area_id,
            "input_asset_ids": list(meta.input_asset_ids),
            "method": meta.method,
            "method_version": meta.method_version,
            "parameters": meta.parameters,
            "created_at": meta.created_at.isoformat(),
            "warnings": list(meta.warnings),
        }

        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 7. 返回 DamageResult。
        return DamageResult(
            artifacts={
                "damage_vector": damage_vector_path,
                "tile_index": tile_index_path,
                "metadata": metadata_path,
            },
            model_name=self.name,
            model_version=self.version,
            meta=meta,
        )
