"""creates habitat map for year of interest"""

import json
import subprocess
import os
from pathlib import Path
import _build_spam_layer

years = ["2000", "2005", "2010", "2020"]

multithread = 16
overwrite = False 

# check if hab map exists
if os.path.isfile(os.path.join('data', 'habitat', f'current_raw.tif')) or overwrite:
    print(f"Jung base habitat map exists - skipping creation")
else:
    print(f"Creating habitat map from Jung data (same across years)...", end=" ")
    import LIFE.prepare_layers.make_current_map
    LIFE.prepare_layers.make_current_map.make_current_map(
        jung_path = Path(os.path.join('data', 'habitat', 'jung_l2_raw.tif')),
        # update_masks_path = Path(os.path.join('data', 'habitat', 'lvl2_changemasks_ver004')),
        update_masks_path = None,
        crosswalk_path = Path(os.path.join('data', 'crosswalk.csv')),
        output_path = Path(os.path.join('data', 'habitat', 'current_raw.tif')),
        concurrency = int(multithread),
        show_progress = True,
    )

# process habitat map
if not os.path.isdir(os.path.join('data', 'habitat', 'lcc_1401.tif')) or not os.path.isdir(os.path.join('data', 'habitat', 'lcc_1402.tif')) or overwrite:
    print(f"Running some aoh-processing..", end=" ")
    command = f"""aoh-habitat-process --habitat {os.path.join('data', 'habitat', 'current_raw.tif')} \
                --scale 0.08333333333333333 \
                --output {os.path.join('data', 'habitat')}"""
    subprocess.run(command, shell=True)
    print("done.")

# prepare the modified 'current' map
with open("data_index.json", 'r') as f:
    data_index = json.load(f)

update_findex = False
for year in years:
    # sum mapspam areas
    spam_year_file = os.path.join('data', 'food', f"mapspam_all_{year}.tif")
    if not os.path.isfile(spam_year_file) or overwrite:
        update_findex = True
        print(f"Summarising Mapspam layers for year {year}...", end=" ")
        _build_spam_layer.summarise_spam_layers(data_index.get(year, {}), year)
        data_index[year]['mapspam_total_percentage'] = spam_year_file
        print("done.")
    else:
        print(f"Mapspam summary for year {year} exists - skipping creation")

if update_findex:
    with open("data_index.json", 'w') as f:
            json.dump(data_index, f, indent=4)

# create the amalgamated habitat map (i.e. jung + spam + hyde)
for year in years:
    current_layers_dir = os.path.join('data', 'food', f'current_layers_{year}')
    if not os.path.isdir(current_layers_dir):
        os.makedirs(current_layers_dir, exist_ok=True)

    # check hyde projection exists
    hyde_prj_path = os.path.join('data', 'food', 'hyde', f'modified_grazing{year}AD.prj') 
    command = f"""echo 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AXIS["Latitude",NORTH],AXIS["Longitude",EAST],AUTHORITY["EPSG","4326"]]' > {hyde_prj_path}"""
    subprocess.run(command, shell=True)

    print(f"Building GAEZ + HYDE layers for year {year}...", end=" ")
    # run this as a subprocess to avoid import problem
    command = f"""python3 ./prepare_layers/build_gaez_hyde.py --gaez {Path(os.path.join("..", 'data', 'food', f'mapspam_all_{year}.tif'))} \
                                                    --hyde {Path(os.path.join("..", 'data', 'food', 'hyde', f'modified_grazing{year}AD.asc'))} \
                                                    --output {Path(os.path.join("..", current_layers_dir))}"""
    subprocess.run(command, cwd = os.path.join(os.getcwd(), 'LIFE'),
                   shell=True)

    # build diff rasters
    import LIFE.utils.raster_diff
    LIFE.utils.raster_diff.raster_diff(
        raster_a_path = Path(os.path.join(current_layers_dir, 'crop.tif')),
        raster_b_path = Path(os.path.join('data', 'habitat', 'lcc_1401.tif')),
        output_path = Path(os.path.join(current_layers_dir, 'crop_diff.tif')),
    )
    LIFE.utils.raster_diff.raster_diff(
        raster_a_path = Path(os.path.join(current_layers_dir, 'pasture.tif')),
        raster_b_path = Path(os.path.join('data', 'habitat', 'lcc_1402.tif')),
        output_path = Path(os.path.join(current_layers_dir, 'pasture_diff.tif')),
    )
    
    # build food map
    import LIFE.prepare_layers.make_food_current_map
    LIFE.prepare_layers.make_food_current_map.make_food_current_map(
        current_lvl1_path = Path(os.path.join('data', 'habitat', 'current_raw.tif')),
        pnv_path = Path(os.path.join('data', 'habitat', 'pnv_raw.tif')),
        crop_adjustment_path = Path(os.path.join(current_layers_dir, 'crop_diff.tif')),
        pasture_adjustment_path = Path(os.path.join(current_layers_dir, 'pasture_diff.tif')),
        output_path = Path(os.path.join('data', 'food', f'current_raw_{year}.tif')),
        processes_count = int(multithread),
    )

    