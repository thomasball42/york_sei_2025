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

warnings.filterwarnings("ignore", category=RuntimeWarning)

years = [
        "2020"
        ]

scenario = "agri_to_pnv"

data_dirs_path = "data/data_dirs"

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

    def process_country(country_geom, weights, deltap_dataset, extra_weights=None):
        """weights are assumed to raw km2 values, extra_weights can be anything"""
        mask = rasterio.features.geometry_mask(
            [country_geom],
            out_shape=target_shape,
            transform=global_transform,
            invert=True
        )

        if extra_weights is None:
            extra_mask = np.ones_like(weights, dtype=bool)
            raw_extra_weights = np.ones_like(weights, dtype=float)
        else:
            extra_mask = ~np.isnan(extra_weights)
            raw_extra_weights = np.where(mask, extra_weights, np.nan)

        raw_weights = np.where(mask, weights, np.nan)
        raw_vals = np.where(mask, deltap_dataset, np.nan)

        valid_indices = (~np.isnan(raw_weights)) & (~np.isnan(raw_vals)) & extra_mask

        if not np.any(valid_indices):
            return np.nan, np.nan, np.nan, np.nan

        physical_area = np.nansum(raw_weights[valid_indices])

        weights_used = raw_weights[valid_indices] * raw_extra_weights[valid_indices]
        vals_used = raw_vals[valid_indices]

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

    # run the thing!
    for year in years:

        output_data = pd.DataFrame()
        output_file = os.path.join(data_dirs_path, "outputs", year, f"processed_results_{year}.csv")

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
                
                for item_name, item_index in spam_data.items():
                    
                    pbar.set_postfix(item=item_name, band=band_name)

                    # print(f"Processing year:{year}, taxa:{band_name}, item:{item_name}...")

                    item_path = item_index['path']
                    
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
                    
                    for iso3 in country_isos:

                        country_geom = countries_data.loc[countries_data[isoa3_str] == iso3.upper(), 'geometry'].values[0]

                        mean_value, mean_sem, pixel_count, physical_area = process_country(country_geom, normalised_data, band_data)

                        output_data.loc[len(output_data), ["ISO3", "item_name", "band_name", "deltaE_mean", "deltaE_mean_sem", "unit", "pixel_count", "physical_area_km2", "sp_count"]] = [
                            iso3, item_name, band_name, mean_value, mean_sem, "deltaE per km2 per sp.", pixel_count, physical_area, sp_count]
                        
                        pbar.update(1)

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

                for file in livestock_files:
                    item_name = os.path.basename(file).split(".tif")[0].split("_")[0].upper()
                    pbar.set_postfix(item=item_name, band=band_name)

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

                    for iso3 in country_isos:

                        country_geom = countries_data.loc[countries_data[isoa3_str] == iso3.upper(), 'geometry'].values[0]

                        mean_value, mean_sem, pixel_count, physical_area = process_country(country_geom, pasture_data, band_data, extra_weights=item_data)

                        output_data.loc[len(output_data), ["ISO3", "item_name", "band_name", "deltaE_mean", "deltaE_mean_sem", "unit", "pixel_count", "physical_area_km2", "sp_count"]] = [
                            iso3, item_name, band_name, mean_value, mean_sem, "deltaE per km2 per sp.", pixel_count, physical_area, sp_count]
                        
                        pbar.update(1)

            output_data.to_csv(output_file, index=False)

if __name__ == "__main__":
    main(data_dirs_path=data_dirs_path, years=years)