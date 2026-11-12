"""Create an inventory with size and SHA-256 for the committed R1 data."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOTS = (
    ROOT / "data/external/osm/geojson",
    ROOT / "outputs/tianjin_2023_flood/stage1",
    ROOT / "outputs/zhuozhou_2023_flood/stage1",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    files = []
    for folder in DATA_ROOTS:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                files.append({
                    "path": path.relative_to(ROOT).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256(path),
                })
    manifest = {
        "schema_version": "1.0",
        "created_date": "2026-10-28",
        "events": ["tianjin_2023_flood", "zhuozhou_2023_flood"],
        "licenses": {
            "sentinel_1_rtc": "Copernicus Sentinel data, free and open under the Copernicus data policy",
            "osm_geojson": "Open Database License (ODbL); attribution: OpenStreetMap contributors",
        },
        "limitations": [
            "Study-area bounding boxes are approximate retrieval extents, not authoritative flood boundaries.",
            "Road blockage status is not inferred; authoritative incident verification is still required.",
            "Prepared rasters are VV backscatter inputs, not flood masks or damage labels.",
        ],
        "files": files,
    }
    out = ROOT / "data/manifests/r1_stage1_delivery.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} ({len(files)} files)")


if __name__ == "__main__":
    main()
