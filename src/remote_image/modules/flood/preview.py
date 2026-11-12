"""可复核的输入与候选图，不用色彩暗示识别置信度。"""
from pathlib import Path
import numpy as np
import rasterio
from rasterio.windows import from_bounds, Window
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.ticker import MaxNLocator

def render_preview(inputs, mask_path, output_path, bounds=None, title="Zhuozhou | rule baseline"):
    with rasterio.open(inputs.post_event.path) as src:
        window = Window(0, 0, src.width, src.height) if bounds is None else from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths().intersection(Window(0,0,src.width,src.height))
        ratio=max(window.width/1100,window.height/1100,1)
        shape=(max(1,int(window.height/ratio)),max(1,int(window.width/ratio)))
        extent=rasterio.windows.bounds(window,src.transform)
    arrays=[]
    for path in (inputs.pre_event.path, inputs.post_event.path):
        with rasterio.open(path) as src:
            arrays.append(src.read(1,window=window,out_shape=shape,masked=True))
    with rasterio.open(mask_path) as src:
        mask=src.read(1,window=window,out_shape=shape)
    fig, axes=plt.subplots(2,2,figsize=(13,10),layout="constrained")
    extent_plot=[extent[0],extent[2],extent[1],extent[3]]
    gray=plt.colormaps["gray"].copy(); gray.set_bad("#999999")
    for ax, array, caption in zip(axes.flat[:2],arrays,["Pre-event | gamma0 dB","Post-event | gamma0 dB"]):
        im=ax.imshow(array,cmap=gray,vmin=-25,vmax=5,extent=extent_plot,interpolation="nearest")
        ax.set_title(caption);fig.colorbar(im,ax=ax,shrink=.78,label="dB")
    delta=arrays[1]-arrays[0]
    im=axes[1,0].imshow(delta,cmap="BrBG_r",vmin=-6,vmax=6,extent=extent_plot,interpolation="nearest")
    axes[1,0].set_title("Post - pre | display limits only")
    fig.colorbar(im,ax=axes[1,0],shrink=.78,label="dB")
    classes=np.where(mask==255,2,mask)
    im=axes[1,1].imshow(classes,cmap=ListedColormap(["#f5f5f5","#0072B2","#999999"]),norm=BoundaryNorm([-.5,.5,1.5,2.5],3),extent=extent_plot,interpolation="nearest")
    axes[1,1].set_title("New-water candidates | accuracy not validated")
    cb=fig.colorbar(im,ax=axes[1,1],ticks=[0,1,2],shrink=.78)
    cb.ax.set_yticklabels(["Not detected","Candidate","Unknown"])
    for ax in axes.flat:
        ax.set_xlabel("Easting (m)");ax.set_ylabel("Northing (m)");ax.ticklabel_format(style="plain",useOffset=False)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=4));ax.tick_params(axis="both",labelsize=9)
    fig.suptitle(title+"\nEPSG:32650 | nearest-neighbour preview | inspect GeoTIFF for full resolution",fontsize=13)
    output_path=Path(output_path);output_path.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(output_path,dpi=150)
    plt.close(fig)
    return output_path
