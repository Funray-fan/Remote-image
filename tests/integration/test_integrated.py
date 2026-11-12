import json
from pathlib import Path
from remote_image.workflows.demo import prepare_demo
from remote_image.workflows.integrated import run_case
from remote_image.core.validation import validate_payload
from remote_image.modules.visualization.stage1 import load_manifest, render_map, feature_ids, query_feature


def test_all_roles_handoff_and_exact_synthetic_exposure(tmp_path):
    config = prepare_demo(tmp_path)
    out = run_case(config)
    summary = json.loads((out/'summary.json').read_text(encoding='utf-8'))
    assert summary['engineering_status']=='pass'
    assert summary['metrics']['candidate_area_m2']==9600
    assert summary['metrics']['building_objects_intersecting']==1
    assert summary['metrics']['road_overlap_length_m']==120
    assert summary['metrics']['population_exposed'] is None
    result=json.loads((out/'pipeline_result.json').read_text(encoding='utf-8'))
    validate_payload('PipelineRunResult',result)
    assert result['status']=='partial'
    assert (out/'file_manifest.json').is_file()
    manifest=load_manifest(out/'layer_manifest.json',allowed_root=tmp_path)
    assert len(manifest['layers'])==6
    markup=render_map(manifest['layers'])
    assert '<svg' in markup and '<image' in markup
    roads=next(l for l in manifest['layers'] if l.id=='roads')
    ids=feature_ids(roads.path)
    assert ids==['way:1']
    assert query_feature(roads.path,ids[0]) is not None


def test_missing_input_produces_failed_status(tmp_path):
    config=prepare_demo(tmp_path)
    (config.parent/'post.tif').unlink()
    import pytest
    with pytest.raises(Exception):
        run_case(config)
    statuses=list((tmp_path/'outputs').rglob('run_status.json'))
    assert len(statuses)==1
    assert json.loads(statuses[0].read_text(encoding='utf-8'))['status']=='failed'
