
import json

from remote_image.core.contracts import (
    DamageRequest,
    InferenceOptions,
    RasterAsset,
    StudyArea,
)
from remote_image.modules.damage import (
    EmptyBaselineDamageAdapter,
    check_adapter_contract,
)


def make_request(tmp_path):
    """构造一个隔离的合成请求，不需要真实影像文件。"""

    post_event = RasterAsset(
        asset_id="post-event-001",
        path=tmp_path / "post_event.tif",
        acquired_at=None,
        source="synthetic_fixture",
        coordinate_reference_system="EPSG:4326",
    )

    return DamageRequest(
        event_id="test-event-001",
        study_area=StudyArea(
            identifier="test-area-001",
            boundary="synthetic boundary",
        ),
        post_event=post_event,
        model_name="baseline_damage_model",
        task="building_damage",
    )


def test_empty_baseline_passes_contract(tmp_path):
    """测试适配器能否通过已有契约检查。"""

    request = make_request(tmp_path)

    adapter = EmptyBaselineDamageAdapter(
        output_root=tmp_path / "outputs"
    )

    report = check_adapter_contract(
        adapter,
        request,
        InferenceOptions(
            tile_size_px=512,
            overlap_ratio=0.2,
            confidence_threshold=0.5,
            device="cpu",
            batch_size=1,
        ),
    )

    assert report.passed, report.errors

    assert "return_type" in report.checks
    assert "artifact_keys" in report.checks
    assert "event_id" in report.checks
    assert "study_area_id" in report.checks
    assert "input_asset_ids" in report.checks
    assert "model_identity" in report.checks


def test_empty_baseline_creates_real_files(tmp_path):
    """测试适配器确实生成了三个文件。"""

    request = make_request(tmp_path)

    adapter = EmptyBaselineDamageAdapter(
        output_root=tmp_path / "outputs"
    )

    result = adapter.predict(request)

    assert result.artifacts["damage_vector"].is_file()
    assert result.artifacts["tile_index"].is_file()
    assert result.artifacts["metadata"].is_file()


def test_empty_baseline_does_not_fabricate_damage(tmp_path):
    """确认空基线没有生成虚构的建筑物损毁记录。"""

    request = make_request(tmp_path)

    adapter = EmptyBaselineDamageAdapter(
        output_root=tmp_path / "outputs"
    )

    result = adapter.predict(request)

    damage_data = json.loads(
        result.artifacts["damage_vector"].read_text(
            encoding="utf-8"
        )
    )

    tile_data = json.loads(
        result.artifacts["tile_index"].read_text(
            encoding="utf-8"
        )
    )

    assert damage_data["type"] == "FeatureCollection"
    assert damage_data["features"] == []

    assert tile_data["type"] == "FeatureCollection"
    assert tile_data["features"] == []


def test_metadata_matches_request(tmp_path):
    """检查元信息中的事件、区域和输入影像编号。"""

    request = make_request(tmp_path)

    adapter = EmptyBaselineDamageAdapter(
        output_root=tmp_path / "outputs"
    )

    result = adapter.predict(request)

    metadata = json.loads(
        result.artifacts["metadata"].read_text(
            encoding="utf-8"
        )
    )

    assert metadata["event_id"] == request.event_id
    assert metadata["study_area_id"] == request.study_area.identifier
    assert "post-event-001" in metadata["input_asset_ids"]
    assert metadata["parameters"]["fixture_only"] is True
