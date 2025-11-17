import numpy as np
import rasterio 
import os
import tqdm

def summarise_spam_layers(year_data, year):
    spam_files = year_data.get("mapspam", {})

    for crop_name, values in tqdm.tqdm(spam_files.items(), desc=f"Summarizing SPAM layers for {year}", total=len(spam_files)):

        file = values.get("path")
        output = None
        with rasterio.open(file) as source:
            if output is None:
                output = np.zeros_like(source.read(1), dtype=np.float64)
                transform = source.transform
                crs = source.crs
            dat = source.read(1)
            if source.nodata is not None:
                dat = np.ma.masked_equal(dat, source.nodata)
            output = np.nansum(np.dstack([output, dat]), 2)
            source.close()
            source = None
    with rasterio.open(
        os.path.join('data', 'food', f"mapspam_all_{year}.tif"),
        "w", driver="GTiff", 
        height=output.shape[0], width=output.shape[1], 
        count=1,  # Number of bands
        dtype=output.dtype,
        crs=crs, transform=transform,
    ) as dst:
        dst.write(output, indexes=1)