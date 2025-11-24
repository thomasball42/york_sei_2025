import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_bounds
import os
import tqdm


def summarise_spam_layers(year_data, year, spam_year_file, target_shape=(2160, 4320)):
    
    spam_files = year_data.get("mapspam", {})
    global_bounds = (-180.0, -90.0, 180.0, 90.0)
    
    global_transform = from_bounds(*global_bounds, target_shape[1], target_shape[0]) # annoyingly neccessary because different spam years have different extents..

    # initialise output
    total_hectares = np.zeros(target_shape, dtype=np.float64)

    for crop_name, values in tqdm.tqdm(spam_files.items(), desc=f"Summarizing SPAM layers for {year}", total=len(spam_files)):
        
        file_path = values.get("path")
        
        with rasterio.open(file_path) as src:
            temp_buffer = np.zeros(target_shape, dtype=np.float64)
            reproject(
                source=rasterio.band(src, 1),
                destination=temp_buffer,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=global_transform,
                dst_crs=src.crs,
                resampling=Resampling.nearest,
                src_nodata=src.nodata,
                dst_nodata=0 # nodata as 0 so it doesn't affect the sum
            )
            
            total_hectares += np.nan_to_num(temp_buffer)

    # these shenanigans are required to allow us to use Michael's habitat map machine without modifying it
    res = (global_transform.a, -global_transform.e) 
    bounds_dict = {
        "left": global_bounds[0],
        "bottom": global_bounds[1],
        "right": global_bounds[2],
        "top": global_bounds[3]
    }
    import PixelAreaCalc.main as PixelAreaCalc 
    pixel_areas = np.array(PixelAreaCalc.get_areas(res=res, bounds=bounds_dict), dtype=np.float64) # in km2
    pixel_areas = pixel_areas[np.newaxis, :].T # turn into a column array
    pixel_areas = np.repeat(pixel_areas, target_shape[1], axis=1)
    proportional_output = 100 * (total_hectares / 100) / pixel_areas # (Hectares / 100 = km2) / Area_km2 * 100 = % pixel
    proportional_output = np.where(proportional_output < 0, -1, proportional_output)

    output_filename = spam_year_file

    with rasterio.open(
        output_filename,
        "w", 
        driver="GTiff", 
        height=target_shape[0], 
        width=target_shape[1], 
        count=1, 
        dtype=np.float32, 
        crs=src.crs,
        transform=global_transform,
        nodata=-1
    ) as dst:
        dst.write(proportional_output.astype(np.float32), indexes=1)