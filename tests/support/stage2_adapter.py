"""仅用于 C1 阶段二集成测试的合成 DamageModel。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from remote_image.core.contracts import (
    DamageRequest,
    DamageResult,
    InferenceOptions,
    ModelManifest,
    ResultMeta,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts"


@dataclass
class FixtureDamageModel:
    name: str = "fixture_damage_model"
    version: str = "1.0.0"

    def predict(
        self, request: DamageRequest, options: InferenceOptions | None = None
    ) -> DamageResult:
        return DamageResult(
            artifacts={
                "damage_vector": FIXTURES / "damage_vector_valid.geojson",
                "tile_index": FIXTURES / "tile_index_valid.geojson",
                "metadata": FIXTURES / "damage_metadata.json",
            },
            model_name=self.name,
            model_version=self.version,
            meta=ResultMeta(
                schema_version="1.0",
                event_id=request.event_id,
                study_area_id=request.study_area.identifier,
                input_asset_ids=tuple(
                    asset.asset_id
                    for asset in (request.pre_event, request.post_event)
                    if asset is not None
                ),
                method=request.task,
                method_version=self.version,
                parameters={
                    "fixture_only": True,
                    "adapter_received_tile_size": options.tile_size_px
                    if options
                    else None,
                },
                created_at=datetime(2026, 11, 17, tzinfo=timezone.utc),
                warnings=("synthetic fixture; not a real assessment",),
            ),
        )


def build_fixture_model(manifest: ModelManifest) -> FixtureDamageModel:
    del manifest
    return FixtureDamageModel()
