"""第二阶段逐建筑损毁结果的空间质检。只检查交付质量，不评估模型准确率。"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from pathlib import Path

import geopandas as gpd
from pyproj import CRS
from shapely.geometry import mapping

from remote_image.core.contracts import CheckItem, DamageResult, SpatialQAReport
from remote_image.core.serialization import to_payload
from remote_image.core.validation import validate_contract


def _layer(path: Path, label: str, crs: CRS) -> gpd.GeoDataFrame:
    if not path.is_file():
        raise ValueError(f"{label} 文件不存在: {path}")
    layer = gpd.read_file(path)
    if layer.crs is None:
        raise ValueError(f"{label} 缺少 CRS: {path}")
    if CRS.from_user_input(layer.crs) != crs:
        raise ValueError(f"{label} CRS 与 expected_crs 不一致: {layer.crs}")
    return layer


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check_damage_geography(
    result: DamageResult, buildings: Path, tile_index: Path,
    expected_crs: str, match_tolerance_m: float, output_dir: Path,
) -> SpatialQAReport:
    """检查事件、ID、几何、建筑匹配和切片覆盖，保存可复核疑点。"""
    validate_contract(result)
    crs = CRS.from_user_input(expected_crs)
    if not crs.is_projected or not crs.axis_info or crs.axis_info[0].unit_name.lower() not in {"metre", "meter"}:
        raise ValueError("expected_crs 必须是以米为单位的投影坐标系")
    if not 0 <= match_tolerance_m <= 1000:
        raise ValueError("match_tolerance_m 必须在 0 到 1000 米之间")
    if result.meta.method != "building_damage":
        raise ValueError("仅检查 building_damage 的逐建筑结果")
    if "damage_vector" not in result.artifacts or "tile_index" not in result.artifacts:
        raise ValueError("阶段二必须交付 damage_vector 和 tile_index")
    if "metadata" not in result.artifacts or not Path(result.artifacts["metadata"]).is_file():
        raise ValueError("阶段二必须交付实际存在的 metadata 文件")
    if Path(result.artifacts["tile_index"]).resolve() != Path(tile_index).resolve():
        raise ValueError("tile_index 参数必须与 DamageResult.artifacts 一致")

    damage = _layer(Path(result.artifacts["damage_vector"]), "damage_vector", crs)
    source = _layer(Path(buildings), "buildings", crs)
    tiles = _layer(Path(tile_index), "tile_index", crs)
    required = {"building_id", "event_id", "study_area_id", "model_name", "model_version", "damage_class", "confidence", "reason"}
    if not required <= set(damage.columns):
        raise ValueError(f"damage_vector 缺少字段: {sorted(required - set(damage.columns))}")
    if "building_id" not in source.columns:
        raise ValueError("buildings 必须包含 building_id")
    if not {"tile_id", "event_id", "study_area_id"} <= set(tiles.columns):
        raise ValueError("tile_index 缺少 tile_id/event_id/study_area_id")
    metadata = json.loads(Path(result.artifacts["metadata"]).read_text(encoding="utf-8"))
    from remote_image.core.validation import validate_payload
    validate_payload("ResultMeta", metadata)
    if any(metadata[key] != getattr(result.meta, key) for key in ("event_id", "study_area_id", "method_version")):
        raise ValueError("metadata 文件与 DamageResult.meta 不一致")

    issues: list[dict] = []
    checks: list[CheckItem] = []
    def flag(row: int | None, building_id: str, code: str, severity: str, geom=None) -> None:
        issues.append({"row": row, "building_id": building_id, "code": code, "severity": severity, "geometry": geom})

    def add_check(name: str, count: int, message: str, *, warning: bool = False) -> None:
        checks.append(CheckItem(name=name, status=("warning" if warning else "fail") if count else "pass",
                                expected=0, actual=count, message=message))

    for name, frame in (("damage_vector", damage), ("buildings", source), ("tile_index", tiles)):
        invalid = frame.geometry.isna() | frame.geometry.is_empty | ~frame.geometry.is_valid
        wrong_type = ~frame.geom_type.isin(["Polygon", "MultiPolygon"])
        for idx in frame.index[invalid | wrong_type]:
            flag(int(idx), str(frame.loc[idx].get("building_id", "")), f"invalid_{name}_geometry", "fail")
    invalid_geometry_count = sum(i["code"].startswith("invalid_") for i in issues)
    add_check("geometry", invalid_geometry_count, "图层几何必须是有效的面")
    if invalid_geometry_count:
        # 无效几何会使距离和空间索引的结果不可靠，先修复源数据。
        damage = damage[damage.geometry.notna() & damage.geometry.is_valid & damage.geom_type.isin(["Polygon", "MultiPolygon"])]
        source = source[source.geometry.notna() & source.geometry.is_valid & source.geom_type.isin(["Polygon", "MultiPolygon"])]
        tiles = tiles[tiles.geometry.notna() & tiles.geometry.is_valid & tiles.geom_type.isin(["Polygon", "MultiPolygon"])]

    for label, frame in (("damage", damage), ("tile", tiles)):
        for idx, row in frame.iterrows():
            if row["event_id"] != result.meta.event_id or row["study_area_id"] != result.meta.study_area_id:
                flag(int(idx), str(row.get("building_id", "")), f"{label}_event_mismatch", "fail", row.geometry)
            if label == "damage" and (row["model_name"] != result.model_name or row["model_version"] != result.model_version):
                flag(int(idx), str(row["building_id"]), "model_mismatch", "fail", row.geometry)
    add_check("identity", sum(i["code"].endswith("mismatch") for i in issues), "事件、研究区及模型身份必须一致")

    classes = {"no-damage", "minor-damage", "major-damage", "destroyed", "un-classified"}
    for idx, row in damage.iterrows():
        confidence = row["confidence"]
        missing = confidence is None or str(confidence) in {"nan", "<NA>"}
        try:
            valid_confidence = missing or (math.isfinite(float(confidence)) and 0 <= float(confidence) <= 1)
        except (TypeError, ValueError):
            valid_confidence = False
        if row["damage_class"] not in classes or (missing and (row["damage_class"] != "un-classified" or not row["reason"])) or not valid_confidence:
            flag(int(idx), str(row["building_id"]), "invalid_prediction", "fail", row.geometry)
    add_check("prediction_fields", sum(i["code"] == "invalid_prediction" for i in issues), "类别与置信度必须符合逐建筑契约")

    for label, frame, key in (("damage", damage, "building_id"), ("buildings", source, "building_id"), ("tile", tiles, "tile_id")):
        values = frame[key].astype("string")
        for idx in frame.index[values.isna() | (values.str.strip() == "")]:
            flag(int(idx), "", f"{label}_missing_id", "fail", frame.loc[idx].geometry)
        for idx in frame.index[values.notna() & values.duplicated(keep=False)]:
            flag(int(idx), str(values.loc[idx]), f"{label}_duplicate_id", "fail", frame.loc[idx].geometry)
    add_check("ids", sum("_id" in i["code"] for i in issues), "ID 必须非空且在本图层唯一")

    source_by_id = {str(row.building_id): row.geometry for _, row in source.iterrows()
                    if row.building_id is not None and str(row.building_id).strip()}
    tile_union = tiles.geometry.union_all() if len(tiles) else None
    for idx, row in damage.iterrows():
        bid, geom = str(row.building_id), row.geometry
        target = source_by_id.get(bid)
        if target is None:
            flag(int(idx), bid, "building_not_found", "fail", geom)
        elif geom.distance(target) > match_tolerance_m:
            flag(int(idx), bid, "building_offset", "fail", geom)
        elif not target.buffer(match_tolerance_m).covers(geom):
            flag(int(idx), bid, "outside_building", "warning", geom)
        if tile_union is None or not tile_union.buffer(match_tolerance_m).covers(geom):
            flag(int(idx), bid, "outside_tiles", "fail", geom)
        elif any(geom.distance(tile.boundary) <= match_tolerance_m for tile in tiles.geometry):
            flag(int(idx), bid, "tile_edge_review", "warning", geom)
    add_check("building_match", sum(i["code"] in {"building_not_found", "building_offset"} for i in issues), "逐建筑 ID 与位置必须匹配")
    add_check("building_boundary", sum(i["code"] == "outside_building" for i in issues), "预测几何超出原始建筑范围，请确认几何来源", warning=True)
    add_check("tile_coverage", sum(i["code"] == "outside_tiles" for i in issues), "预测几何须位于切片覆盖范围")
    add_check("tile_edges", sum(i["code"] == "tile_edge_review" for i in issues), "靠近切片边缘的建筑需人工查看", warning=True)

    # 不同 ID 的预测面大面积相交可能表示切片拼接重复；边界接触不算重叠。
    overlap_pairs = set()
    if len(damage):
        for left, right in damage.sindex.query(damage.geometry, predicate="intersects").T:
            if left >= right:
                continue
            a, b = damage.iloc[left], damage.iloc[right]
            if str(a.building_id) != str(b.building_id) and a.geometry.intersection(b.geometry).area > 1e-6:
                overlap_pairs.add((int(damage.index[left]), int(damage.index[right])))
                flag(int(damage.index[left]), str(a.building_id), "prediction_overlap", "warning", a.geometry)
                flag(int(damage.index[right]), str(b.building_id), "prediction_overlap", "warning", b.geometry)
    add_check("prediction_overlap", len(overlap_pairs), "不同建筑预测面发生面积重叠", warning=True)

    counts = Counter(item["code"] for item in issues)
    status = "fail" if any(item["severity"] == "fail" for item in issues) else "warning" if issues or len(damage) == 0 else "pass"
    warnings = ["空结果只能证明接口可读，不能证明模型完成推理。"] if len(damage) == 0 else []
    if len(tiles) == 0:
        warnings.append("切片索引为空，无法核查实际切片覆盖。")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    csv_path, geojson_path, report_path = out / "suspect_samples.csv", out / "suspect_buildings.geojson", out / "spatial_qa.json"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["row", "building_id", "code", "severity"])
        writer.writeheader()
        writer.writerows({key: item[key] for key in writer.fieldnames} for item in issues)
    _write_json(geojson_path, {"type": "FeatureCollection", "name": "suspect_buildings", "crs": {"type": "name", "properties": {"name": crs.to_string()}},
                               "features": [{"type": "Feature", "geometry": mapping(item["geometry"]), "properties": {key: item[key] for key in ("row", "building_id", "code", "severity")}}
                                            for item in issues if item["geometry"] is not None and item["geometry"].is_valid]})
    report = SpatialQAReport(status=status, checks=tuple(checks),
                             metrics={"damage_count": len(damage), "source_building_count": len(source), "tile_count": len(tiles),
                                      "issue_count": len(issues), "issue_counts": dict(sorted(counts.items())), "overlap_pair_count": len(overlap_pairs),
                                      "expected_crs": crs.to_string(), "match_tolerance_m": match_tolerance_m},
                             warnings=tuple(warnings), artifacts={"suspect_samples": csv_path, "suspect_buildings": geojson_path})
    validate_contract(report)
    _write_json(report_path, to_payload(report))
    return report
