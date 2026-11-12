"""Convert Overpass JSON into small map-ready GeoJSON layers.

The input is the raw Overpass response saved under data/external/osm. Output
uses WGS84 (EPSG:4326), as required by RFC 7946 GeoJSON.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


RESCUE_AMENITIES = {"hospital", "fire_station", "police", "clinic"}


def feature(geometry: dict, element: dict, kind: str) -> dict:
    tags = element.get("tags", {})
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "osm_id": element.get("id"),
            "osm_type": element.get("type"),
            "layer": kind,
            **tags,
        },
    }


def write_layer(path: Path, features: list[dict]) -> None:
    data = {
        "type": "FeatureCollection",
        "name": path.stem,
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": features,
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def convert(source: Path, out_dir: Path) -> None:
    data = json.loads(source.read_text(encoding="utf-8"))
    buildings: list[dict] = []
    roads: list[dict] = []
    rescue: list[dict] = []
    for element in data.get("elements", []):
        tags = element.get("tags", {})
        if element.get("type") == "node":
            amenity = tags.get("amenity")
            emergency = tags.get("emergency")
            if amenity in RESCUE_AMENITIES or emergency == "ambulance_station":
                rescue.append(feature({"type": "Point", "coordinates": [element["lon"], element["lat"]]}, element, "rescue_point"))
            continue
        geometry = element.get("geometry") or []
        coords = [[p["lon"], p["lat"]] for p in geometry if "lon" in p and "lat" in p]
        if len(coords) < 2:
            continue
        amenity = tags.get("amenity")
        emergency = tags.get("emergency")
        if amenity in RESCUE_AMENITIES or emergency == "ambulance_station":
            cx = sum(p[0] for p in coords) / len(coords)
            cy = sum(p[1] for p in coords) / len(coords)
            rescue.append(feature({"type": "Point", "coordinates": [cx, cy]}, element, "rescue_point"))
        if "building" in tags and len(coords) >= 4 and coords[0] == coords[-1]:
            buildings.append(feature({"type": "Polygon", "coordinates": [coords]}, element, "building"))
        if "highway" in tags:
            roads.append(feature({"type": "LineString", "coordinates": coords}, element, "road"))
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = source.stem
    write_layer(out_dir / f"{stem}_buildings.geojson", buildings)
    write_layer(out_dir / f"{stem}_roads.geojson", roads)
    write_layer(out_dir / f"{stem}_rescue_points.geojson", rescue)
    print(f"{source.name}: buildings={len(buildings)} roads={len(roads)} rescue_points={len(rescue)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--output-dir", type=Path, default=Path("data/external/osm/geojson"))
    args = ap.parse_args()
    for source in args.inputs:
        convert(source, args.output_dir)


if __name__ == "__main__":
    main()
