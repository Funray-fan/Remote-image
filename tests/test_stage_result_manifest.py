from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    import jsonschema
except ImportError:  # Local core checks can run without the dev extra.
    jsonschema = None


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(jsonschema is not None, "install .[dev] to validate JSON Schema")
class StageResultManifestSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(
            (ROOT / "schemas" / "v1" / "stage-result-manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.fixture = json.loads(
            (
                ROOT
                / "tests"
                / "fixtures"
                / "contracts"
                / "stage_result_manifest_valid.json"
            ).read_text(encoding="utf-8")
        )

    def test_valid_manifest(self) -> None:
        jsonschema.Draft202012Validator(self.schema).validate(self.fixture)

    def test_missing_artifacts_is_rejected(self) -> None:
        invalid = dict(self.fixture)
        invalid.pop("artifacts")
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(self.schema).validate(invalid)


if __name__ == "__main__":
    unittest.main()
