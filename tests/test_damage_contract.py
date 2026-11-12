from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from remote_image.core.contracts import (
    DamageRequest,
    DamageResult,
    InferenceOptions,
    RasterAsset,
    ResultMeta,
    StudyArea,
)
from remote_image.modules.damage import check_adapter_contract


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "contracts"


class FixtureDamageModel:
    name = "fixture_damage_model"
    version = "1.0.0"

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
            model_version="1.0.0",
            meta=ResultMeta(
                schema_version="2.0",
                event_id=request.event_id,
                study_area_id=request.study_area.identifier,
                input_asset_ids=(request.post_event.asset_id,),
                method=request.task,
                method_version="1.0.0",
                parameters={"fixture_only": True},
                created_at=datetime(2026, 10, 25, tzinfo=timezone.utc),
            ),
        )


def make_request() -> DamageRequest:
    area = StudyArea("fixture_area", str(FIXTURES / "study_area.geojson"))
    post = RasterAsset(
        asset_id="fixture_post_event",
        path=FIXTURES / "post_event.tif",
        acquired_at=None,
        source="synthetic_fixture",
        coordinate_reference_system="EPSG:4326",
    )
    return DamageRequest(
        event_id="fixture_event",
        study_area=area,
        post_event=post,
        building_footprints=FIXTURES / "buildings.geojson",
        model_name="fixture_damage_model",
        model_version="1.0.0",
    )


class DamageAdapterContractTests(unittest.TestCase):
    def test_fixture_adapter_passes_contract(self) -> None:
        report = check_adapter_contract(
            FixtureDamageModel(), make_request(), validate_artifacts=False
        )
        self.assertTrue(report.passed, report.errors)

    def test_fixture_files_are_isolated_and_synthetic(self) -> None:
        metadata = json.loads((FIXTURES / "damage_metadata.json").read_text(encoding="utf-8"))
        self.assertTrue(metadata["fixture_only"])


try:
    import jsonschema
except ImportError:  # Local core checks can run without the dev extra.
    jsonschema = None


@unittest.skipUnless(jsonschema is not None, "install .[dev] to validate JSON Schema")
class DamageSchemaTests(unittest.TestCase):
    def _validate(self, schema_name: str, fixture_name: str) -> None:
        schema = json.loads((ROOT / "schemas" / "v1" / schema_name).read_text(encoding="utf-8"))
        fixture = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(fixture)

    def test_valid_request_and_result(self) -> None:
        self._validate("damage-request.schema.json", "damage_request_valid.json")
        self._validate("damage-result.schema.json", "damage_result_valid.json")
        self._validate("damage-vector.schema.json", "damage_vector_valid.geojson")
        self._validate("tile-index.schema.json", "tile_index_valid.geojson")

    def test_invalid_damage_class_is_rejected(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "v1" / "damage-vector.schema.json").read_text(encoding="utf-8")
        )
        fixture = json.loads(
            (FIXTURES / "damage_vector_invalid_class.geojson").read_text(encoding="utf-8")
        )
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(schema).validate(fixture)
