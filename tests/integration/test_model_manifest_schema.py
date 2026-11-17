from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "contracts"


class ModelManifestSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(
            (ROOT / "schemas" / "v1" / "model-manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.fixture = json.loads(
            (FIXTURES / "model_manifest_valid.json").read_text(encoding="utf-8")
        )

    def test_valid_model_manifest(self) -> None:
        Draft202012Validator(self.schema).validate(self.fixture)

    def test_missing_weights_is_rejected(self) -> None:
        invalid = dict(self.fixture)
        invalid.pop("weights")
        with self.assertRaises(ValidationError):
            Draft202012Validator(self.schema).validate(invalid)

    def test_absolute_weight_path_is_rejected(self) -> None:
        invalid = json.loads(json.dumps(self.fixture))
        invalid["weights"][0]["path"] = "C:/models/weights.pt"
        with self.assertRaises(ValidationError):
            Draft202012Validator(self.schema).validate(invalid)


if __name__ == "__main__":
    unittest.main()
