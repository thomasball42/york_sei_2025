import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import reproject, Resampling
import rasterio.features
import os
import json
from PixelAreaCalc.main import get_areas
import _process_livestock_data
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
from tqdm import tqdm
import warnings
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore", category=RuntimeWarning)

years = [
        "2010",
        # "2020"
        ]

scenario = "all_agri_to_pnv"

versionid = ""

data_dirs_path = "data/data_dirs"

boundary_data = {
                #  "adm0": {"path": Path("data/inputs/country_data/geoBoundariesCGAZ_ADM0.shp"), # currently doesn't work because the .shp has a difference structure
                #           "url": "https://github.com/wmgeolab/geoBoundaries/raw/main/releaseData/CGAZ/geoBoundariesCGAZ_ADM0.zip",},
                 "adm1": {"path": Path("data/inputs/boundary_data/geoBoundariesCGAZ_ADM1.shp"),
                          "url": "https://github.com/wmgeolab/geoBoundaries/raw/main/releaseData/CGAZ/geoBoundariesCGAZ_ADM1.zip",},
                 "adm2": {"path": Path("data/inputs/boundary_data/geoBoundariesCGAZ_ADM2.shp"),
                          "url": "https://github.com/wmgeolab/geoBoundaries/raw/main/releaseData/CGAZ/geoBoundariesCGAZ_ADM2.zip",}
                          }

NUM_THREADS = 48

if len(sys.argv) > 1:
    if sys.argv[1] in years:
        years = [sys.argv[1]]
    else:
        print(f"Year {sys.argv[1]} not recognised, defaulting to all years: {years}")

def main(data_dirs_path=data_dirs_path, years = years, 
         shapefile_path = os.path.join("data", "inputs", "adm_region_data", "geoBoundariesCGAZ_ADM0.shp"), 
         boundary_level="adm0"):
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    # global params
    target_shape = (2160, 4320)
    global_bounds = (-180.0, -90.0, 180.0, 90.0)
    global_transform = from_bounds(*global_bounds, target_shape[1], target_shape[0])
    pixel_areas = get_areas(res=(global_transform.a, -global_transform.e), # these are never actually used really
                                    R = 6371.0, 
                                    bounds = {
                                                "left": global_bounds[0],
                                                "bottom": global_bounds[1],
                                                "right": global_bounds[2],
                                                "top": global_bounds[3]
                                            })

    # load global data
    with open("data_index.json", 'r') as f:
        data_index = json.load(f)

    if not os.path.isfile(shapefile_path):
        import _get_subadmin_boundaries
        _get_subadmin_boundaries.get_boundary_data()

    boundaries_data = gpd.read_file(shapefile_path)

    n_boundaries = len(boundaries_data)

    # keyed by shapeID rather than shapeName: shapeName is not unique (e.g. many
    # countries have a "Northern" ADM1, many US states have a "Washington" county),
    # so grouping by name would silently merge unrelated regions. shapeID is unique per row.
    #
    # rasterizing each adm_region against a *local* window (its own bbox, padded by
    # 1px) rather than the full 2160x4320 grid is what makes adm2 tractable: at adm2
    # there are ~49k regions, and materialising one full-size boolean mask per region
    # (as this used to do) needs ~440GB peak RSS. Only the flat indices are kept
    # around, and their total size across all regions is bounded by the grid size
    # itself (~9.3M pixels), so this is essentially free at any boundary level.
    global_height, global_width = target_shape
    adm_region_flat_indices = {}
    for _, row in tqdm(boundaries_data.iterrows(), total=n_boundaries, desc="Precomputing adm_region masks"):
        geom = row['geometry']
        minx, miny, maxx, maxy = geom.bounds

        row_start, col_start = rasterio.transform.rowcol(global_transform, minx, maxy)
        row_stop, col_stop = rasterio.transform.rowcol(global_transform, maxx, miny)

        row_start = max(int(row_start) - 1, 0)
        col_start = max(int(col_start) - 1, 0)
        row_stop = min(int(row_stop) + 2, global_height)
        col_stop = min(int(col_stop) + 2, global_width)

        win_height = row_stop - row_start
        win_width = col_stop - col_start

        if win_height <= 0 or win_width <= 0:
            adm_region_flat_indices[row['shapeID']] = np.array([], dtype=np.int64)
            continue

        window = rasterio.windows.Window(col_start, row_start, win_width, win_height)
        window_transform = rasterio.windows.transform(window, global_transform)

        local_mask = rasterio.features.geometry_mask(
            [geom],
            out_shape=(win_height, win_width),
            transform=window_transform,
            all_touched=True,
            invert=True
        )

        local_rows, local_cols = np.nonzero(local_mask)
        flat_idx = (local_rows + row_start).astype(np.int64) * global_width + (local_cols + col_start)
        adm_region_flat_indices[row['shapeID']] = flat_idx

    def process_adm_region(idx, weights_flat, vals_flat, extra_weights_flat=None):
        """weights are assumed to be raw km2 values, extra_weights can be anything.
        idx are the precomputed flat indices of this adm_region's pixels."""
        w = weights_flat[idx]
        v = vals_flat[idx]

        if extra_weights_flat is None:
            extra_valid = np.ones_like(w, dtype=bool)
            raw_extra_weights = np.ones_like(w, dtype=float)
        else:
            raw_extra_weights = extra_weights_flat[idx]
            extra_valid = ~np.isnan(raw_extra_weights)

        # w == 0 means the crop/livestock genuinely isn't present at that pixel (not missing
        # data), so it must be excluded here too -- otherwise vals_used/variance end up covering
        # ~the whole region mask rather than the intersection of the region and where this
        # item actually has weight, and mean_sem stops meaning anything crop-specific.
        valid_indices = (~np.isnan(w)) & (~np.isnan(v)) & extra_valid & ((w * raw_extra_weights) > 0)

        if not np.any(valid_indices):
            return np.nan, np.nan, np.nan, np.nan

        physical_area = np.nansum(w[valid_indices])

        weights_used = w[valid_indices] * raw_extra_weights[valid_indices]
        vals_used = v[valid_indices]

        weights_normalised = weights_used / np.nansum(weights_used)

        mean_value = np.nansum(vals_used * weights_normalised)

        pixel_count = vals_used.size

        variance = np.var(vals_used)
        mean_sem = np.sqrt(variance * np.sum(weights_normalised ** 2))

        return mean_value, mean_sem, int(pixel_count), physical_area


    def normalise_spam_data_01(data_array, pixel_areas, target_shape, unit_conv=100, no_data = -1):
                """
                # in this instance I use a ones array (cf the pixel areas), the delta-p array is 
                # calculated at 'per-km2'
                # """
                pixel_areas = pixel_areas[np.newaxis, :].T # turn into a column array
                pixel_areas = np.repeat(pixel_areas, target_shape[1], axis=1)
                proportional_output = (data_array / unit_conv) / pixel_areas # (Hectares / 100 = km2) / Area_km2 * 100 = % pixel
                proportional_output = np.where(proportional_output < 0, no_data, proportional_output)
                return proportional_output

    output_columns = ["shapeName", "shapeID", "shapeGroup", "shapeType", 
                        "item_name", "band_name", "deltaE_mean", "deltaE_mean_sem", 
                        "unit", "pixel_count", "physical_area_km2", "sp_count"]
    max_workers = min(NUM_THREADS, os.cpu_count() or 1)

    # run the thing!
    for year in years:

        output_file = os.path.join(data_dirs_path, "outputs", year, f"{scenario}_processed_{year}{versionid}_{boundary_level}.csv")
        # written out incrementally, one band at a time, below - at adm2 scale
        # (49k boundaries x ~55 items x 5 bands is ~13M rows) holding every row
        # for the whole year in memory before writing is its own, smaller OOM risk
        if os.path.exists(output_file):
            os.remove(output_file)

        if not os.path.exists(os.path.join(data_dirs_path, "outputs", year)):
            os.makedirs(os.path.join(data_dirs_path, "outputs", year), exist_ok=True)

        deltap_data = os.path.join(data_dirs_path, year, "deltap_final", f"scaled_{scenario}_0.25.tif")
        deltap_dataset = rasterio.open(deltap_data)
        band_names = deltap_dataset.descriptions
        band_count = deltap_dataset.count

        spam_data = data_index[year]['mapspam']
        spam_data["ALLC"] = {
            "path": os.path.join("data", "food", "mapspam", f"mapspam_all_{year}_total_hectares.tif"),
            "unit": 'harvested area in hectares / pixel'
        }

        hyde_data = data_index[year]['hyde']
        pasture_path = hyde_data['pasture']['path']
        livestock_files, uncertainty_files = _process_livestock_data.get_livestock_data(year)

        total_items = (len(spam_data) + len(livestock_files)) * n_boundaries * band_count

        with tqdm(total=total_items, desc=f"Calculating delta-p ({year}, {n_boundaries} boundaries)", unit="item") as pbar:

            for band_idx in range(1, band_count + 1):

                output_rows = []

                # allows the processing of different taxa
                band_name = band_names[band_idx - 1]
                band_data = np.zeros(target_shape, dtype=np.float64)
                reproject(
                    source=rasterio.band(deltap_dataset, band_idx),
                    destination=band_data,
                    src_transform=deltap_dataset.transform,
                    src_crs=deltap_dataset.crs,
                    dst_transform=global_transform,
                    dst_crs=deltap_dataset.crs,
                    resampling=Resampling.nearest,
                    src_nodata=deltap_dataset.nodata,
                    dst_nodata=np.nan,
                )

                sp_totals = pd.read_csv(os.path.join(data_dirs_path, year, "deltap", scenario, "0.25", "totals.csv"))
                sp_count = sp_totals.loc[sp_totals['taxa'] == band_name, 'count'].values[0]

                def process_item(item_name, item_path):
                    """reproject + normalise + per-adm_region stats for one crop item, independent of every other item"""
                    with rasterio.open(item_path) as src:
                        item_dataset = np.full(target_shape, np.nan, dtype=np.float64)
                        reproject(
                            source=rasterio.band(src, 1),
                            destination=item_dataset,
                            src_transform=src.transform,
                            src_crs=src.crs,
                            dst_transform=global_transform,
                            dst_crs=src.crs,
                            resampling=Resampling.nearest,
                            src_nodata=src.nodata,
                            dst_nodata=np.nan,
                        )

                    const_array = np.ones_like(pixel_areas)
                    normalised_data = normalise_spam_data_01(item_dataset, const_array, target_shape, unit_conv=100, no_data=np.nan) # using ones here - deltap is already in per-km2, so we just need km2 for the crop vals

                    weights_flat = normalised_data.ravel()
                    vals_flat = band_data.ravel()

                    rows = []
                    for _, row in boundaries_data.iterrows():
                        shapeName, shapeID, shapeGroup, shapeType = row['shapeName'], row['shapeID'], row['shapeGroup'], row['shapeType']
                        mean_value, mean_sem, pixel_count, physical_area = process_adm_region(adm_region_flat_indices[shapeID], weights_flat, vals_flat)
                        rows.append((shapeName, shapeID, shapeGroup, shapeType, item_name, band_name, mean_value, mean_sem, "deltaE per km2 per sp.", pixel_count, physical_area, sp_count))
                    return item_name, rows

                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {executor.submit(process_item, item_name, item_index['path']): item_name for item_name, item_index in spam_data.items()}
                    for future in as_completed(futures):
                        item_name, rows = future.result()
                        pbar.set_postfix(item=item_name, band=band_name)
                        output_rows.extend(rows)
                        pbar.update(n_boundaries)

                with rasterio.open(pasture_path) as src:
                        pasture_data = np.zeros(target_shape, dtype=np.float64)
                        reproject(
                            source=rasterio.band(src, 1),
                            destination=pasture_data,
                            src_transform=src.transform,
                            src_crs=src.crs,
                            dst_transform=global_transform,
                            dst_crs=src.crs,
                            resampling=Resampling.nearest,
                            src_nodata=src.nodata,
                            dst_nodata=np.nan,
                        )

                def process_livestock_item(file):
                    """reproject + normalise + per-adm_region stats for one livestock file, independent of every other file"""
                    item_name = os.path.basename(file).split(".tif")[0].split("_")[0].upper()

                    with rasterio.open(file) as src:
                        item_dataset = np.full(target_shape, np.nan, dtype=np.float64)
                        reproject(
                            source=rasterio.band(src, 1),
                            destination=item_dataset,
                            src_transform=src.transform,
                            src_crs=src.crs,
                            dst_transform=global_transform,
                            dst_crs=src.crs,
                            resampling=Resampling.nearest,
                            src_nodata=src.nodata,
                            dst_nodata=np.nan,
                        )

                    const_array = np.ones_like(pixel_areas)
                    item_data = normalise_spam_data_01(item_dataset, const_array, target_shape, unit_conv=1, no_data=np.nan) # using ones here - deltap is already in per-km2, so we just need km2 for the crop vals

                    weights_flat = pasture_data.ravel()
                    vals_flat = band_data.ravel()
                    extra_weights_flat = item_data.ravel()

                    rows = []
                    for _, row in boundaries_data.iterrows():
                        shapeName, shapeID, shapeGroup, shapeType = row['shapeName'], row['shapeID'], row['shapeGroup'], row['shapeType']
                        mean_value, mean_sem, pixel_count, physical_area = process_adm_region(adm_region_flat_indices[shapeID], weights_flat, vals_flat, extra_weights_flat=extra_weights_flat)
                        rows.append((shapeName, shapeID, shapeGroup, shapeType, item_name, band_name, mean_value, mean_sem, "deltaE per km2 per sp.", pixel_count, physical_area, sp_count))
                    return item_name, rows

                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {executor.submit(process_livestock_item, file): file for file in livestock_files}
                    for future in as_completed(futures):
                        item_name, rows = future.result()
                        pbar.set_postfix(item=item_name, band=band_name)
                        output_rows.extend(rows)
                        pbar.update(n_boundaries)

                band_df = pd.DataFrame(output_rows, columns=output_columns)
                band_df.to_csv(output_file, mode="a", index=False, header=(band_idx == 1))

if __name__ == "__main__":

    for boundary_level, boundary_info in boundary_data.items():
        if not os.path.isfile(boundary_info["path"]):
            import _get_subadmin_boundaries
            _get_subadmin_boundaries.get_boundary_data(url=boundary_info["url"])
        
        main(data_dirs_path=data_dirs_path, years=years, shapefile_path=boundary_info["path"], boundary_level=boundary_level)