import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import reproject, Resampling
import rasterio.features
import os
import json
from PixelAreaCalc.main import get_areas
import _process_livestock_data

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
versionid = "_adm0"

data_dirs_path = "data/data_dirs"

NUM_THREADS = 48

if len(sys.argv) > 1:
    if sys.argv[1] in years:
        years = [sys.argv[1]]
    else:
        print(f"Year {sys.argv[1]} not recognised, defaulting to all years: {years}")

def main(data_dirs_path=data_dirs_path, years = years):
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

    countries_shapefile = os.path.join("data", "inputs", "country_data", "geoBoundariesCGAZ_ADM0.shp")

    if not os.path.isfile(countries_shapefile):
        import _get_data
        _get_data.get_country_data()

    countries_data = gpd.read_file(countries_shapefile)

    isoa3_str = "shapeGroup"
    country_isos = countries_data[isoa3_str].unique()

    country_masks = {}
    for iso3 in tqdm(country_isos, desc="Precomputing country masks"):
        country_geom = countries_data.loc[countries_data[isoa3_str] == iso3.upper(), 'geometry'].values[0]
        country_masks[iso3] = rasterio.features.geometry_mask(
            [country_geom],
            out_shape=target_shape,
            transform=global_transform,
            invert=True
        )

    # flat pixel indices per country, computed once so per-item/per-band processing
    # only ever touches the (small) subset of the global raster each country covers,
    # instead of re-scanning the full 2160x4320 grid for every country every time
    country_flat_indices = {iso3: np.flatnonzero(mask) for iso3, mask in country_masks.items()}

    def process_country(idx, weights_flat, vals_flat, extra_weights_flat=None):
        """weights are assumed to be raw km2 values, extra_weights can be anything.
        idx are the precomputed flat indices of this country's pixels."""
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
        # ~the whole country mask rather than the intersection of the country and where this
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

    output_columns = ["ISO3", "item_name", "band_name", "deltaE_mean", "deltaE_mean_sem", "unit", "pixel_count", "physical_area_km2", "sp_count"]
    max_workers = min(NUM_THREADS, os.cpu_count() or 1)

    # run the thing!
    for year in years:

        output_file = os.path.join(data_dirs_path, "outputs", year, f"{scenario}_processed_{year}{versionid}.csv")
        output_rows = []

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

        total_items = (len(spam_data) + len(livestock_files)) * len(country_isos) * band_count

        with tqdm(total=total_items, desc=f"Calculating delta-p ({year}, {len(country_isos)} countries)", unit="item") as pbar:

            for band_idx in range(1, band_count + 1):

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
                    """reproject + normalise + per-country stats for one crop item, independent of every other item"""
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
                    for iso3 in country_isos:
                        mean_value, mean_sem, pixel_count, physical_area = process_country(country_flat_indices[iso3], weights_flat, vals_flat)
                        rows.append((iso3, item_name, band_name, mean_value, mean_sem, "deltaE per km2 per sp.", pixel_count, physical_area, sp_count))
                    return item_name, rows

                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {executor.submit(process_item, item_name, item_index['path']): item_name for item_name, item_index in spam_data.items()}
                    for future in as_completed(futures):
                        item_name, rows = future.result()
                        pbar.set_postfix(item=item_name, band=band_name)
                        output_rows.extend(rows)
                        pbar.update(len(country_isos))

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
                    """reproject + normalise + per-country stats for one livestock file, independent of every other file"""
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
                    for iso3 in country_isos:
                        mean_value, mean_sem, pixel_count, physical_area = process_country(country_flat_indices[iso3], weights_flat, vals_flat, extra_weights_flat=extra_weights_flat)
                        rows.append((iso3, item_name, band_name, mean_value, mean_sem, "deltaE per km2 per sp.", pixel_count, physical_area, sp_count))
                    return item_name, rows

                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {executor.submit(process_livestock_item, file): file for file in livestock_files}
                    for future in as_completed(futures):
                        item_name, rows = future.result()
                        pbar.set_postfix(item=item_name, band=band_name)
                        output_rows.extend(rows)
                        pbar.update(len(country_isos))

            output_data = pd.DataFrame(output_rows, columns=output_columns)
            output_data.to_csv(output_file, index=False)

if __name__ == "__main__":
    main(data_dirs_path=data_dirs_path, years=years)