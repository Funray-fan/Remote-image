"""Run R1 registration, validation and optional pair preparation."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from remote_image.modules.data.r1_preprocessing import (  # noqa: E402
    AssetRecord,
    GridSpec,
    PreparedInputs,
    StudyArea,
    prepare_pair,
    raster_asset_from_path,
    register_asset,
    validate_raster,
    write_report,
)

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/sign?href="
EVENTS = {
    "tianjin_2023_flood": {"bbox": [116.70, 38.80, 117.80, 39.50], "target_crs": "EPSG:32650", "pre": "S1A_IW_GRDH_1SDV_20230724T101409_20230724T101434_049564_05F5BB_rtc", "post": "S1A_IW_GRDH_1SDV_20230805T101410_20230805T101435_049739_05FB20_rtc"},
    "zhuozhou_2023_flood": {"bbox": [115.75, 39.30, 116.20, 39.70], "target_crs": "EPSG:32650", "pre": "S1A_IW_GRDH_1SDV_20230724T101409_20230724T101434_049564_05F5BB_rtc", "post": "S1A_IW_GRDH_1SDV_20230805T101410_20230805T101435_049739_05FB20_rtc"},
}


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=90) as response:
        return json.load(response)


def signed_href(href: str) -> str:
    return get_json(SAS + urllib.parse.quote(href, safe=""))["href"]


def source_asset(item_id: str, pol: str = "vv"):
    item = get_json(f"{STAC}/collections/sentinel-1-rtc/items/{item_id}")
    href = item["assets"][pol]["href"]
    props = item["properties"]
    asset = raster_asset_from_path(Path(f"remote_{item_id}_{pol}.tif"), item_id + "_" + pol, "Copernicus Sentinel-1 RTC", (pol.upper(),), source_uri=signed_href(href), acquired_at=props.get("datetime"))
    return asset, item


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", choices=sorted(EVENTS), required=True)
    ap.add_argument("--prepare-pair", action="store_true")
    ap.add_argument("--polarization", choices=("vv", "vh"), default="vv")
    args = ap.parse_args()
    spec = EVENTS[args.event]
    event_root = ROOT / "data" / "raw" / args.event
    output_root = ROOT / "outputs" / args.event / "stage1"
    output_root.mkdir(parents=True, exist_ok=True)
    area = StudyArea(args.event, {"bbox": spec["bbox"]})
    pre, pre_item = source_asset(spec["pre"], args.polarization)
    post, post_item = source_asset(spec["post"], args.polarization)
    source_assets = [pre, post]
    validation_reports = []
    catalog = output_root / "asset_catalog.json"
    for asset, item in ((pre, pre_item), (post, post_item)):
        record = AssetRecord(asset.asset_id, f"{STAC}/collections/sentinel-1-rtc/items/{item['id']}", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "Copernicus Sentinel data", None, {"bbox_wgs84": spec["bbox"]}, (item["properties"].get("datetime"), item["properties"].get("datetime")), "verified", ("Source is a signed remote COG; full source hash is not computed.",), None)
        register_asset(asset, record, catalog)
        report = validate_raster(asset, area, (args.polarization.upper(),))
        write_report(report, output_root / f"{asset.asset_id}_validation.json")
        validation_reports.append(report)
    prepared = None
    if args.prepare_pair:
        prepared_dir = output_root / "prepared" / args.polarization
        existing_meta = prepared_dir / "metadata.json"
        if all((prepared_dir / name).exists() for name in ("pre_event.tif", "post_event.tif", "valid_mask.tif", "metadata.json")):
            meta = json.loads(existing_meta.read_text(encoding="utf-8"))
            grid_data = meta["parameters"]["grid"]
            grid = GridSpec(tuple(grid_data["transform"]), int(grid_data["width"]), int(grid_data["height"]), float(grid_data["pixel_size_x_m"]), float(grid_data["pixel_size_y_m"]))
            prepared = PreparedInputs(
                raster_asset_from_path(prepared_dir / "pre_event.tif", pre.asset_id + "_prepared", pre.source, pre.bands, acquired_at=pre.acquired_at),
                raster_asset_from_path(prepared_dir / "post_event.tif", post.asset_id + "_prepared", post.source, post.bands, acquired_at=post.acquired_at),
                args.event, grid, prepared_dir / "valid_mask.tif", existing_meta,
            )
        else:
            prepared = prepare_pair(pre, post, area, spec["target_crs"], None, "bilinear", prepared_dir)
        prepared_assets = [prepared.pre_event, prepared.post_event]
        for asset in prepared_assets:
            if asset is None:
                continue
            rel = asset.path.relative_to(ROOT).as_posix()
            record = AssetRecord(asset.asset_id, f"{STAC}/collections/sentinel-1-rtc/items/{spec['pre'] if asset.asset_id.startswith(spec['pre']) else spec['post']}", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "Copernicus Sentinel data", None, {"bbox_wgs84": spec["bbox"]}, (asset.acquired_at, asset.acquired_at), "usable", ("Prepared from a remote signed COG; source is Sentinel-1 RTC VV.",), rel)
            register_asset(asset, record, catalog)
        prepared_payload = prepared.to_dict()
        prepared_payload["pre_event"]["path"] = prepared.pre_event.path.relative_to(ROOT).as_posix() if prepared.pre_event else None
        prepared_payload["post_event"]["path"] = prepared.post_event.path.relative_to(ROOT).as_posix()
        prepared_payload["valid_mask"] = prepared.valid_mask.relative_to(ROOT).as_posix() if prepared.valid_mask else None
        prepared_payload["metadata"] = prepared.metadata.relative_to(ROOT).as_posix()
        (output_root / "prepared_inputs.json").write_text(json.dumps(prepared_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    raster_payload = {asset.asset_id: asset.to_dict() for asset in source_assets}
    (output_root / "raster_assets.json").write_text(json.dumps(raster_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    statuses = [r.status for r in validation_reports]
    summary = {"schema_version": "1.0", "event_id": args.event, "stage": "stage1", "owner": "R1", "status": "pass" if all(s == "pass" for s in statuses) else "warning", "input_asset_ids": [a.asset_id for a in source_assets], "artifacts": {"asset_catalog": catalog.relative_to(ROOT).as_posix(), "raster_assets": (output_root / "raster_assets.json").relative_to(ROOT).as_posix()}, "reports": [p.relative_to(ROOT).as_posix() for p in output_root.glob("*_validation.json")], "warnings": ["Source COGs are remote signed assets; full source sha256 is not computed."]}
    if prepared is not None:
        summary["artifacts"].update({"prepared_inputs": (output_root / "prepared_inputs.json").relative_to(ROOT).as_posix(), "pre_event": prepared.pre_event.path.relative_to(ROOT).as_posix(), "post_event": prepared.post_event.path.relative_to(ROOT).as_posix(), "valid_mask": prepared.valid_mask.relative_to(ROOT).as_posix()})
    (output_root / "r1_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
