"""Create a small reproducible input case; never represents a real disaster."""
from pathlib import Path
import json
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box, LineString
from remote_image.modules.data import r1_preprocessing as r1


def prepare_demo(root: Path) -> Path:
    root = Path(root).resolve()
    folder = root/'work'/'synthetic-input'
    folder.mkdir(parents=True, exist_ok=True)
    transform = from_origin(500000, 4400000, 10, 10)
    pre = np.full((64,64), 0.1, dtype='float32')
    post = pre.copy()
    post[20:28,20:32] = 0.005
    for name, data in [('pre',pre), ('post',post), ('mask',np.ones((64,64),dtype='uint8'))]:
        path=folder/(name+'.tif')
        with rasterio.open(path,'w',driver='GTiff',width=64,height=64,count=1,dtype=data.dtype,
                           crs='EPSG:32650',transform=transform,nodata=0) as ds:
            ds.write(data,1)
            ds.set_band_description(1,'valid_pre_post' if name=='mask' else 'VV')
    a=r1.raster_asset_from_path(folder/'pre.tif','synthetic_pre','synthetic',('VV',),acquired_at='2023-07-24T00:00:00Z')
    b=r1.raster_asset_from_path(folder/'post.tif','synthetic_post','synthetic',('VV',),acquired_at='2023-08-05T00:00:00Z')
    manifest=r1.PreparedInputs(a,b,'synthetic_area',r1.GridSpec(tuple(transform),64,64,10,10),folder/'mask.tif',folder/'metadata.json')
    (folder/'prepared_inputs.json').write_text(json.dumps(manifest.to_dict()),encoding='utf-8')
    for kind,geometry in [('buildings',box(500220,4399740,500250,4399770)),
                          ('roads',LineString([(500100,4399760),(500400,4399760)]))]:
        gpd.GeoDataFrame({'osm_type':['way'],'osm_id':[1]},geometry=[geometry],crs='EPSG:32650').to_file(folder/(kind+'.gpkg'),driver='GPKG')
    rel=lambda name: (folder/name).relative_to(root).as_posix()
    cfg={'project_root':'../..','event_id':'synthetic_integration','synthetic':True,
         'input':{'prepared_inputs_path':rel('prepared_inputs.json'),'pre_path':rel('pre.tif'),
                  'post_path':rel('post.tif'),'valid_mask_path':rel('mask.tif'),
                  'backscatter_quantity':'gamma0','value_scale':'linear_power','polarization':'VV',
                  'source_revision':'synthetic-generated-1'},
         'analysis':{'area_crs':'EPSG:32650','aoi_kind':'raster_extent','connectivity':4,
                     'min_patch_area_m2':0,'selected_water_threshold_db':-18},
         'context':{'buildings_path':rel('buildings.gpkg'),'roads_path':rel('roads.gpkg')},
         'output':{'root':'outputs/synthetic_integration/stage1'},
         'context_source':'synthetic generated fixture'}
    target=folder/'config.json'
    target.write_text(json.dumps(cfg),encoding='utf-8')
    return target
