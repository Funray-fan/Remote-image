"""取得固定 R1 提交的涿州样例，原始影像可从已有学习目录复用。"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = "237cff7c433a6e041418f128d01a99453738a0a8"
FILES = {
    "pre_event.tif": "outputs/zhuozhou_2023_flood/stage1/prepared/vv/pre_event.tif",
    "post_event.tif": "outputs/zhuozhou_2023_flood/stage1/prepared/vv/post_event.tif",
    "valid_mask.tif": "outputs/zhuozhou_2023_flood/stage1/prepared/vv/valid_mask.tif",
    "prepared_inputs.json": "outputs/zhuozhou_2023_flood/stage1/prepared_inputs.json",
    "raw_buildings.geojson": "data/external/osm/geojson/zhuozhou/zhuozhou_osm_features_buildings.geojson",
    "raw_roads.geojson": "data/external/osm/geojson/zhuozhou/zhuozhou_osm_features_roads.geojson",
}
EXPECTED = {
    "pre_event.tif": "613c9c5338ff14f31728810b54d2380dc5d535c3f1553c69458dd76e24aed384",
    "post_event.tif": "e785da785719a8cf0675006f6819540282a473b705d41d569d99e049bb53fb23",
    "valid_mask.tif": "25d570bea82fb22efca9d1aa2a75eed1f8566a2e14d0e8eefd75949fdebeba47",
}
def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as src:
        for block in iter(lambda:src.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--learning-dir",type=Path,default=ROOT.parent/"Remote-image-r2-learning"/"data"/"zhuozhou")
    args=parser.parse_args()
    target=ROOT/"data"/"zhuozhou"
    target.mkdir(parents=True,exist_ok=True)
    records={}
    for name,remote in FILES.items():
        path=target/name
        if not path.exists():
            local=args.learning_dir/name
            if name in EXPECTED and local.is_file():
                shutil.copy2(local,path)
            else:
                content=subprocess.check_output(["git","show",f"{REVISION}:{remote}"],cwd=ROOT)
                path.write_bytes(content)
        sha=digest(path)
        if name in EXPECTED and sha != EXPECTED[name]:
            raise ValueError(f"SHA256 mismatch: {name}")
        records[name]={"path":str(path.relative_to(ROOT)).replace("\\","/"),
                       "sha256":sha,"size_bytes":path.stat().st_size,
                       "source_url":f"https://github.com/Funray-fan/Remote-image/blob/{REVISION}/{remote}"}
    manifest={"source_revision":REVISION,"retrieved_at":datetime.now(timezone.utc).isoformat(),
              "files":records,
              "licenses":{"raster":"Copernicus Sentinel data",
                          "context":"ODbL-1.0; OpenStreetMap contributors"},
              "limitations":["OSM source observation dates are unspecified; not a verified 2023 asset inventory.",
                             "The R1 text-file manifest hashes can differ with LF/CRLF; these are hashes of the actual retrieved files."]}
    manifest_dir=ROOT/"data"/"manifests"
    manifest_dir.mkdir(parents=True,exist_ok=True)
    (manifest_dir/"r2_zhuozhou_sources.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"source_revision":REVISION,"files":{k:{"bytes":v["size_bytes"],"sha256":v["sha256"]} for k,v in records.items()}},indent=2))
if __name__=="__main__":
    main()
