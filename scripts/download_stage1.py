"""Download/query stage-one source data.

The script uses Planetary Computer STAC for Sentinel-1/2 metadata and signed
COG URLs. It intentionally writes metadata and small previews by default; use
--download-cog only after checking disk space because a full Sentinel-1 COG is
about 1.8 GB before clipping.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import urllib.parse
import urllib.request

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/sign?href="

EVENTS = {
    "tianjin_2023_flood": (116.70, 38.80, 117.80, 39.50),
    "zhuozhou_2023_flood": (115.75, 39.30, 116.20, 39.70),
}


def get_json(url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def search(collection: str, bbox: tuple[float, float, float, float], start: str, end: str) -> list[dict]:
    result = get_json(f"{STAC}/search", {
        "collections": [collection], "bbox": list(bbox),
        "datetime": f"{start}/{end}", "limit": 100,
    })
    return result.get("features", [])


def signed(href: str) -> str:
    return get_json(SAS + urllib.parse.quote(href, safe=""))["href"]


def download(url: str, path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=180) as src, path.open("wb") as dst:
        while chunk := src.read(1024 * 1024):
            dst.write(chunk)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", choices=sorted(EVENTS), required=True)
    ap.add_argument("--start", default="2023-07-20")
    ap.add_argument("--end", default="2023-08-20")
    ap.add_argument("--download-cog", action="store_true")
    args = ap.parse_args()
    bbox = EVENTS[args.event]
    root = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw" / args.event / "imagery"
    records = []
    for collection in ("sentinel-1-rtc", "sentinel-2-l2a"):
        for feature in search(collection, bbox, args.start, args.end):
            props = feature.get("properties", {})
            rec = {"collection": collection, "id": feature["id"], "datetime": props.get("datetime"),
                   "cloud_cover": props.get("eo:cloud_cover"), "orbit": props.get("sat:relative_orbit"),
                   "orbit_state": props.get("sat:orbit_state"), "assets": {}}
            for key, asset in feature.get("assets", {}).items():
                if key in {"vv", "vh", "B02", "B03", "B04", "B08", "visual", "rendered_preview"}:
                    rec["assets"][key] = asset.get("href")
            records.append(rec)
            if args.download_cog and collection == "sentinel-1-rtc" and feature["id"].endswith("_rtc"):
                for pol in ("vv", "vh"):
                    href = feature["assets"].get(pol, {}).get("href")
                    if href:
                        path = root / f"{feature['id']}_{pol}.tif"
                        if not path.exists():
                            download(signed(href), path)
    out = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw" / args.event / "stac_search.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"event_id": args.event, "bbox": bbox, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out} ({len(records)} STAC items)")


if __name__ == "__main__":
    main()
