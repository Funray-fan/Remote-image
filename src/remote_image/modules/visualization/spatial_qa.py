"""Read R2 reports and projected suspect geometry for human review."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .stage1 import MapLayer, VisualizationInputError, _read_json
from .stage2 import _local_file, _validate_v2


@dataclass(frozen=True)
class SpatialQAView:
    report: dict[str, Any]
    report_path: Path
    samples_path: Path | None
    suspect_layer: MapLayer | None
    features: tuple[dict[str, Any], ...]


def load_spatial_qa_view(path: Path, *, allowed_root: Path) -> SpatialQAView:
    root = allowed_root.resolve()
    path = _local_file(path, root, root)
    report = _read_json(path)
    _validate_v2("SpatialQAReport", report)
    samples = report["artifacts"].get("suspect_samples")
    samples_path = _local_file(samples, path.parent, root) if samples else None
    raw = report["artifacts"].get("suspect_buildings")
    layer = None
    features = ()
    if raw:
        vector = _local_file(raw, path.parent, root)
        try:
            import geopandas as gpd
            frame = gpd.read_file(vector)
            if frame.crs is None:
                raise VisualizationInputError("R2 疑点图层缺少真实 CRS")
            if not frame.empty:
                if not {"building_id", "code", "severity"} <= set(frame.columns):
                    raise VisualizationInputError("R2 疑点图层缺少建筑 ID、原因或级别")
                if not (frame.geometry.notna() & ~frame.geometry.is_empty & frame.geometry.is_valid).all():
                    raise VisualizationInputError("R2 疑点图层含无效几何")
                import json
                collection = json.loads(frame.to_crs("EPSG:4326").to_json(drop_id=True))
                features = tuple(collection["features"])
                layer = MapLayer(id="r2-suspects", title="R2 空间疑点（待人工复核）", kind="vector",
                    path=vector, crs="EPSG:4326", source="R2 空间质检", visible=False,
                    palette={"warning": "#a855f7", "fail": "#dc2626"}, color_property="severity")
        except VisualizationInputError:
            raise
        except Exception as exc:
            raise VisualizationInputError(f"无法读取 R2 疑点图层：{exc}") from exc
    return SpatialQAView(report, path, samples_path, layer, features)
