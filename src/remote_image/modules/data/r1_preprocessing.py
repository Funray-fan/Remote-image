"""R1 data registration and raster preprocessing for stage one.

The module follows the R1 contracts in the project specification. Rasterio is
loaded at call time so catalog-only operations can still run without GIS
dependencies; raster validation and preparation require rasterio.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Sequence


AssetStatus = Literal["planned", "verified", "acquired", "usable"]
SourceType = Literal["satellite", "uav_orthomosaic", "public_orthomosaic"]
ResamplingName = Literal["nearest", "bilinear", "cubic", "average"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


def _require_rasterio():
    try:
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.warp import calculate_default_transform, reproject, transform_bounds
    except ImportError as exc:
        raise RuntimeError(
            "R1 raster operations require rasterio, pyproj and numpy. "
            "Install with: python -m pip install -r requirements-r1.txt"
        ) from exc
    return rasterio, Resampling, calculate_default_transform, reproject, transform_bounds


@dataclass
class AssetRecord:
    asset_id: str
    source_url: str | None
    retrieved_at: str | None
    license_id: str
    sha256: str | None
    spatial_coverage: dict[str, Any] | str
    time_range: tuple[str | None, str | None]
    status: AssetStatus
    limitations: tuple[str, ...] = ()
    local_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass
class RasterAsset:
    asset_id: str
    path: Path
    acquired_at: str | None
    source: str
    coordinate_reference_system: str
    pixel_size_m: float | None
    bands: tuple[str, ...]
    footprint: Path | None = None
    source_type: SourceType = "satellite"
    is_substitute: bool = False
    quality_notes: str | None = None
    source_uri: str | None = None
    nodata: float | int | None = None
    width: int | None = None
    height: int | None = None
    count: int | None = None
    dtype: str | None = None
    transform: tuple[float, ...] | None = None
    bounds: tuple[float, float, float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass
class StudyArea:
    identifier: str
    boundary: dict[str, Any] | str
    coordinate_reference_system: str = "EPSG:4326"

    def bbox(self) -> tuple[float, float, float, float]:
        boundary = self.boundary
        if isinstance(boundary, str):
            boundary = json.loads(Path(boundary).read_text(encoding="utf-8"))
        if isinstance(boundary, dict) and "bbox" in boundary:
            values = boundary["bbox"]
        elif isinstance(boundary, dict) and boundary.get("type") == "Feature":
            values = boundary["geometry"].get("coordinates")
            return _geometry_bbox(boundary["geometry"])
        elif isinstance(boundary, dict) and boundary.get("type") in {"Polygon", "MultiPolygon"}:
            return _geometry_bbox(boundary)
        else:
            values = boundary
        if not isinstance(values, (list, tuple)) or len(values) != 4:
            raise ValueError("StudyArea boundary must contain a bbox [minx, miny, maxx, maxy]")
        return tuple(float(v) for v in values)  # type: ignore[return-value]


@dataclass
class GridSpec:
    transform: tuple[float, ...]
    width: int
    height: int
    pixel_size_x_m: float
    pixel_size_y_m: float

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass
class PreparedInputs:
    pre_event: RasterAsset | None
    post_event: RasterAsset
    study_area_id: str
    grid: GridSpec
    valid_mask: Path | None
    metadata: Path

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass
class CheckItem:
    name: str
    status: Literal["pass", "warning", "fail"]
    expected: Any
    actual: Any
    message: str


@dataclass
class RasterValidationReport:
    status: Literal["pass", "warning", "fail"]
    checks: list[CheckItem]
    metrics: dict[str, Any]
    warnings: list[str]
    artifacts: dict[str, Path]

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


def _geometry_bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    coords = geometry.get("coordinates", [])
    values: list[tuple[float, float]] = []

    def visit(node: Any) -> None:
        if isinstance(node, (list, tuple)) and len(node) >= 2 and all(isinstance(v, (int, float)) for v in node[:2]):
            values.append((float(node[0]), float(node[1])))
        elif isinstance(node, (list, tuple)):
            for child in node:
                visit(child)

    visit(coords)
    if not values:
        raise ValueError("boundary geometry has no coordinates")
    xs, ys = zip(*values)
    return min(xs), min(ys), max(xs), max(ys)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _raster_uri(asset: RasterAsset) -> str:
    return asset.source_uri or str(asset.path)


def _open_raster(asset: RasterAsset):
    rasterio, *_ = _require_rasterio()
    return rasterio.open(_raster_uri(asset))


def raster_asset_from_path(
    path: Path,
    asset_id: str,
    source: str,
    bands: Sequence[str] = (),
    source_type: SourceType = "satellite",
    acquired_at: str | None = None,
    source_uri: str | None = None,
) -> RasterAsset:
    """Read raster metadata and create a standard RasterAsset."""
    asset = RasterAsset(
        asset_id=asset_id,
        path=Path(path),
        acquired_at=acquired_at,
        source=source,
        coordinate_reference_system="unknown",
        pixel_size_m=None,
        bands=tuple(bands),
        source_type=source_type,
        source_uri=source_uri,
    )
    with _open_raster(asset) as ds:
        crs = ds.crs.to_string() if ds.crs else "unknown"
        px = abs(float(ds.transform.a))
        py = abs(float(ds.transform.e))
        labels = tuple(bands) if bands else tuple(f"band_{i}" for i in range(1, ds.count + 1))
        return RasterAsset(
            **{**asset.__dict__, "coordinate_reference_system": crs,
               "pixel_size_m": max(px, py), "bands": labels,
               "nodata": ds.nodata, "width": ds.width, "height": ds.height,
               "count": ds.count, "dtype": ds.dtypes[0],
               "transform": tuple(ds.transform),
               "bounds": tuple(ds.bounds)},
        )


def register_asset(asset: RasterAsset, record: AssetRecord, catalog: Path) -> AssetRecord:
    """Register one raster and append/update a JSON asset catalog."""
    path = Path(asset.path)
    if record.local_path is None and path.exists():
        record.local_path = path.as_posix()
    if record.sha256 is None and path.is_file():
        record.sha256 = _sha256(path)
    catalog = Path(catalog)
    catalog.parent.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    if catalog.exists():
        existing = json.loads(catalog.read_text(encoding="utf-8"))
        entries = existing.get("assets", existing) if isinstance(existing, dict) else existing
    entries = [item for item in entries if item.get("asset_id") != record.asset_id]
    entries.append(record.to_dict())
    catalog.write_text(json.dumps({"schema_version": "1.0", "assets": entries}, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def update_asset_status(catalog: Path, asset_id: str, status: AssetStatus, note: str | None = None) -> AssetRecord:
    """Update status through the catalog rather than mutating source metadata."""
    data = json.loads(Path(catalog).read_text(encoding="utf-8"))
    for item in data.get("assets", []):
        if item.get("asset_id") == asset_id:
            item["status"] = status
            if note:
                limitations = list(item.get("limitations") or [])
                limitations.append(note)
                item["limitations"] = limitations
            Path(catalog).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return AssetRecord(
                asset_id=item["asset_id"], source_url=item.get("source_url"), retrieved_at=item.get("retrieved_at"),
                license_id=item.get("license_id", item.get("license", "unknown")), sha256=item.get("sha256"),
                spatial_coverage=item.get("spatial_coverage", {}), time_range=tuple(item.get("time_range", (None, None))),
                status=item["status"], limitations=tuple(item.get("limitations", ())), local_path=item.get("local_path"),
            )
    raise KeyError(f"asset_id not found: {asset_id}")


def validate_raster(asset: RasterAsset, area: StudyArea, required_bands: tuple[str, ...] = ()) -> RasterValidationReport:
    """Check readability, CRS, bands, pixel size, and study-area coverage."""
    checks: list[CheckItem] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}
    artifacts: dict[str, Path] = {}
    try:
        with _open_raster(asset) as ds:
            crs = ds.crs.to_string() if ds.crs else None
            px = (abs(float(ds.transform.a)), abs(float(ds.transform.e)))
            bounds = tuple(float(v) for v in ds.bounds)
            metrics.update({"width": ds.width, "height": ds.height, "count": ds.count, "dtype": ds.dtypes[0], "crs": crs, "pixel_size_m": px, "bounds": bounds, "nodata": ds.nodata})
            checks.append(CheckItem("readable", "pass", True, True, "Raster opened successfully"))
            checks.append(CheckItem("crs", "pass" if crs else "fail", "defined", crs, "CRS is present" if crs else "CRS is missing"))
            checks.append(CheckItem("dimensions", "pass" if ds.width > 0 and ds.height > 0 else "fail", ">0", [ds.width, ds.height], "Raster dimensions are valid"))
            transform_values = tuple(float(v) for v in ds.transform)
            determinant = transform_values[0] * transform_values[4] - transform_values[1] * transform_values[3]
            transform_valid = all(math.isfinite(v) for v in transform_values) and determinant != 0
            checks.append(CheckItem("transform", "pass" if transform_valid else "fail", "valid affine transform", transform_values, "Affine transform is valid" if transform_valid else "Invalid transform"))
            band_names = set(asset.bands)
            missing = [band for band in required_bands if band not in band_names]
            checks.append(CheckItem("bands", "pass" if not missing else "fail", list(required_bands), list(asset.bands), "Required bands are available" if not missing else f"Missing bands: {missing}"))
            area_bounds = area.bbox()
            area_crs = area.coordinate_reference_system
            if crs and area_crs != crs:
                try:
                    _, _, _, _, transform_bounds = _require_rasterio()
                    area_bounds = transform_bounds(area_crs, crs, *area_bounds, densify_pts=21)
                except Exception as exc:
                    warnings.append(f"AOI transform failed: {exc}")
            overlap = not (bounds[2] <= area_bounds[0] or bounds[0] >= area_bounds[2] or bounds[3] <= area_bounds[1] or bounds[1] >= area_bounds[3])
            checks.append(CheckItem("coverage", "pass" if overlap else "fail", "overlap study area", overlap, "Raster overlaps study area" if overlap else "Raster does not cover study area"))
            if ds.nodata is None:
                warnings.append("NoData is not declared; downstream masks must be checked before flood statistics.")
    except Exception as exc:
        checks.append(CheckItem("readable", "fail", True, False, str(exc)))
    status: Literal["pass", "warning", "fail"] = "fail" if any(c.status == "fail" for c in checks) else ("warning" if warnings else "pass")
    return RasterValidationReport(status, checks, metrics, warnings, artifacts)


def _grid_from_area(area: StudyArea, target_crs: str, pixel_size: float, source_asset: RasterAsset) -> GridSpec:
    rasterio, _, calculate_default_transform, _, transform_bounds = _require_rasterio()
    bounds = transform_bounds(area.coordinate_reference_system, target_crs, *area.bbox(), densify_pts=21)
    left, bottom, right, top = bounds
    width = max(1, int(math.ceil((right - left) / pixel_size)))
    height = max(1, int(math.ceil((top - bottom) / pixel_size)))
    transform = rasterio.Affine(pixel_size, 0, left, 0, -pixel_size, top)
    return GridSpec(tuple(transform), width, height, pixel_size, pixel_size)


def prepare_pair(
    pre: RasterAsset,
    post: RasterAsset,
    area: StudyArea,
    target_crs: str,
    grid: GridSpec | None,
    resampling: ResamplingName,
    output_dir: Path,
) -> PreparedInputs:
    """Clip/reproject a pre/post pair into one shared analysis grid."""
    rasterio, Resampling, _, reproject, transform_bounds = _require_rasterio()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if grid is None:
        pixel_size = pre.pixel_size_m or 10.0
        grid = _grid_from_area(area, target_crs, pixel_size, pre)
    rs = getattr(Resampling, resampling)
    outputs: dict[str, Path] = {}
    valid_masks: list[Any] = []
    for label, asset in (("pre_event", pre), ("post_event", post)):
        out_path = output_dir / f"{label}.tif"
        with _open_raster(asset) as src:
            # Read only the source window intersecting the AOI. This is
            # important for remote COGs: reprojecting the full scene would
            # otherwise trigger a multi-gigabyte scan.
            src_bounds = transform_bounds(area.coordinate_reference_system, src.crs, *area.bbox(), densify_pts=21)
            from rasterio.windows import from_bounds
            window = from_bounds(*src_bounds, transform=src.transform)
            window = window.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
            source_array = src.read(1, window=window, boundless=False)
            source_transform = src.window_transform(window)
            profile = src.profile.copy()
            profile.pop("blockxsize", None)
            profile.pop("blockysize", None)
            profile.update(driver="GTiff", crs=target_crs, transform=rasterio.Affine(*grid.transform), width=grid.width, height=grid.height, count=1, dtype="float32", nodata=-32768.0, tiled=True, blockxsize=256, blockysize=256, compress="deflate", BIGTIFF="IF_SAFER")
            valid = __import__("numpy").zeros((grid.height, grid.width), dtype="uint8")
            with rasterio.open(out_path, "w", **profile) as dst:
                destination = __import__("numpy").full((grid.height, grid.width), -32768.0, dtype="float32")
                reproject(
                    source=source_array, destination=destination,
                    src_transform=source_transform, src_crs=src.crs,
                    src_nodata=src.nodata, dst_transform=rasterio.Affine(*grid.transform),
                    dst_crs=target_crs, dst_nodata=-32768.0, resampling=rs,
                )
                valid[(destination != -32768.0) & __import__("numpy").isfinite(destination)] = 1
                dst.write(destination, 1)
                dst.set_band_description(1, asset.bands[0] if asset.bands else "band_1")
            valid_masks.append(valid)
        outputs[label] = out_path
    import numpy as np
    valid_path = output_dir / "valid_mask.tif"
    mask = np.logical_and(valid_masks[0] == 1, valid_masks[1] == 1).astype("uint8")
    profile = {"driver": "GTiff", "height": grid.height, "width": grid.width, "count": 1, "dtype": "uint8", "crs": target_crs, "transform": rasterio.Affine(*grid.transform), "nodata": 0, "compress": "deflate", "tiled": True}
    with rasterio.open(valid_path, "w", **profile) as dst:
        dst.write(mask, 1)
        dst.set_band_description(1, "valid_pre_post")
    metadata = output_dir / "metadata.json"
    warnings = []
    if pre.coordinate_reference_system != post.coordinate_reference_system:
        warnings.append("Pre/post source CRS differ; both were reprojected to target_crs.")
    metadata.write_text(json.dumps({"schema_version": "1.0", "event_id": area.identifier, "study_area_id": area.identifier, "input_asset_ids": [pre.asset_id, post.asset_id], "method": "clip_reproject_align", "method_version": "1.0", "parameters": {"target_crs": target_crs, "resampling": resampling, "grid": grid.to_dict()}, "created_at": _now(), "warnings": warnings, "artifacts": {"pre_event": outputs["pre_event"].name, "post_event": outputs["post_event"].name, "valid_mask": valid_path.name}}, ensure_ascii=False, indent=2), encoding="utf-8")
    prepared_pre = raster_asset_from_path(outputs["pre_event"], pre.asset_id + "_prepared", pre.source, pre.bands, pre.source_type, pre.acquired_at)
    prepared_post = raster_asset_from_path(outputs["post_event"], post.asset_id + "_prepared", post.source, post.bands, post.source_type, post.acquired_at)
    return PreparedInputs(prepared_pre, prepared_post, area.identifier, grid, valid_path, metadata)


def write_report(report: RasterValidationReport, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path

