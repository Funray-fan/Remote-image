"""从 core.contracts 生成 v2 JSON Schema；生成文件不得手工修改。"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
import types
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from remote_image.core import contracts  # noqa: E402


def kebab(name: str) -> str:
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name).lower()


def schema_for(annotation: Any, defs: dict[str, Any]) -> dict[str, Any]:
    if annotation is Any:
        return {}
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, types.UnionType):
        return {"anyOf": [schema_for(item, defs) for item in args]}
    if origin is Literal:
        values = list(args)
        result: dict[str, Any] = {"enum": values}
        if values and all(isinstance(value, str) for value in values):
            result["type"] = "string"
        return result
    if dataclasses.is_dataclass(annotation):
        name = annotation.__name__
        if name not in defs:
            defs[name] = {}
            defs[name] = object_schema(annotation, defs, top_level=False)
        return {"$ref": f"#/$defs/{name}"}
    if annotation is Path:
        return {"type": "string", "minLength": 1}
    if annotation is datetime:
        return {"type": "string", "format": "date-time"}
    if origin is dict:
        return {"type": "object", "additionalProperties": schema_for(args[1], defs)}
    if origin in (list, tuple):
        if origin is tuple and args and args[-1] is not Ellipsis:
            return {
                "type": "array",
                "prefixItems": [schema_for(item, defs) for item in args],
                "items": False,
                "minItems": len(args),
                "maxItems": len(args),
            }
        return {"type": "array", "items": schema_for(args[0], defs)}
    if annotation is str:
        return {"type": "string", "minLength": 1}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is type(None):
        return {"type": "null"}
    return {}


def object_schema(cls: type, defs: dict[str, Any], *, top_level: bool) -> dict[str, Any]:
    hints = get_type_hints(cls)
    properties = {field.name: schema_for(hints[field.name], defs) for field in dataclasses.fields(cls)}
    if top_level and "schema_version" not in properties:
        properties = {"schema_version": {"const": "2.0", "type": "string"}, **properties}
    elif top_level and "schema_version" in properties:
        properties["schema_version"] = {"const": "2.0", "type": "string"}
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def geojson_schemas() -> dict[str, dict[str, Any]]:
    geometry = {
        "type": "object",
        "required": ["type", "coordinates"],
        "properties": {"type": {"type": "string"}, "coordinates": {"type": "array"}},
        "additionalProperties": False,
    }

    def collection(properties: dict[str, Any]) -> dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "",
            "type": "object",
            "required": ["schema_version", "type", "features"],
            "properties": {
                "schema_version": {"const": "2.0"},
                "type": {"const": "FeatureCollection"},
                "features": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["type", "geometry", "properties"],
                        "properties": {
                            "type": {"const": "Feature"},
                            "geometry": geometry,
                            "properties": {"type": "object", "required": list(properties), "properties": properties, "additionalProperties": False},
                        },
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        }

    common = {"event_id": {"type": "string", "minLength": 1}, "study_area_id": {"type": "string", "minLength": 1}}
    damage = collection({
        **common,
        "building_id": {"type": "string", "minLength": 1},
        "damage_class": {"enum": ["no-damage", "minor-damage", "major-damage", "destroyed", "un-classified"]},
        "confidence": {"anyOf": [{"type": "number", "minimum": 0, "maximum": 1}, {"type": "null"}]},
        "reason": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "model_name": {"type": "string", "minLength": 1},
        "model_version": {"type": "string", "minLength": 1},
    })
    tile = collection({**common, "tile_id": {"type": "string", "minLength": 1}, "row": {"type": "integer", "minimum": 0}, "column": {"type": "integer", "minimum": 0}})
    return {"damage-vector": damage, "tile-index": tile}


def build() -> dict[str, str]:
    output: dict[str, str] = {}
    for name, cls in vars(contracts).items():
        if not isinstance(cls, type) or cls.__module__ != contracts.__name__ or not dataclasses.is_dataclass(cls):
            continue
        defs: dict[str, Any] = {}
        schema = object_schema(cls, defs, top_level=True)
        schema.update({"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"https://remote-image.local/schemas/v2/{kebab(name)}.schema.json", "title": name})
        if defs:
            schema["$defs"] = defs
        output[f"{kebab(name)}.schema.json"] = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
    for name, schema in geojson_schemas().items():
        schema["$id"] = f"https://remote-image.local/schemas/v2/{name}.schema.json"
        output[f"{name}.schema.json"] = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generated = build()
    destinations = (ROOT / "schemas" / "v2", ROOT / "src" / "remote_image" / "schema_data" / "v2")
    if args.check:
        mismatches = [str(folder / name) for folder in destinations for name, data in generated.items() if not (folder / name).is_file() or (folder / name).read_text(encoding="utf-8") != data]
        if mismatches:
            print("Schema 未同步:\n" + "\n".join(mismatches))
            return 1
        print(f"Schema 同步检查通过: {len(generated)} files x {len(destinations)}")
        return 0
    for folder in destinations:
        folder.mkdir(parents=True, exist_ok=True)
        for name, data in generated.items():
            (folder / name).write_text(data, encoding="utf-8")
    print(f"生成 {len(generated)} 个 Schema，并同步到源码包")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
