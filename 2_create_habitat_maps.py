"""creates habitat map for year of interest"""

import json
import subprocess
import os
from pathlib import Path
import _build_spam_layer
from _gdal_aligner import realign_geotiff_origin
from osgeo import gdal

gdal.SetCacheMax(5 * 1024 * 1024 * 1024)

years = ["2000", "2005", "2010", "2020"]

multithread = 32
overwrite = False 

# check if hab map exists
if os.path.isfile(os.path.join('data', 'habitat', f'current_raw.tif')) or overwrite:
    print(f"Jung base habitat map exists - skipping creation")
else:
    print(f"Creating habitat map from Jung data...")
    import LIFE.prepare_layers.make_current_map
    LIFE.prepare_layers.make_current_map.make_current_map(
        jung_path = Path(os.path.join('data', 'inputs', 'habitat', 'jung_l2_raw.tif')),
        # update_masks_path = Path(os.path.join('data', 'habitat', 'lvl2_changemasks_ver004')),
        update_masks_path = None,
        crosswalk_path = Path(os.path.join('data', 'crosswalk.csv')),
        output_path = Path(os.path.join('data', 'habitat', 'current_raw.tif')),
        concurrency = int(multithread /2 ),
        show_progress = True,
    )

# process habitat maps
if not os.path.isfile(os.path.join('data', 'habitat', 'lcc_1401.tif')) or not os.path.isfile(os.path.join('data', 'habitat', 'lcc_1402.tif')) or overwrite:
    print(f"Running some aoh-processing..")
    command = f"""aoh-habitat-process --habitat {os.path.join('data', 'habitat', 'current_raw.tif')} \
                --scale 0.083333333333333 \
                --output {os.path.join('data', 'habitat')}"""
    subprocess.run(command, shell=True)
    ###### Janky realignment code ######
    f = []
    for path, subdirs, files in os.walk(os.path.join("data", "habitat")):
        for name in files:
            f.append(os.path.join(path, name))
    habitat_files = [_ for _ in f if "lcc_" in _ and ".tif" in _ and "pnv" not in _]
    for hab_file in habitat_files:
        realign_geotiff_origin(hab_file, tolerance=1E-6)
    print("done.")
else:
    print(f"AOH-processed habitat maps exist - skipping creation")  

if not os.path.isdir(os.path.join('data', 'habitat', 'pnv')) or overwrite:
    os.makedirs(os.path.join('data', 'habitat', 'pnv'), exist_ok=True)
    print("Processing potential natural vegetation map...")
    command = f"""aoh-habitat-process --habitat {os.path.join('data', "inputs", 'habitat', 'pnv_raw.tif')} \
                --scale 0.083333333333333 \
                --output {os.path.join('data', 'habitat', 'pnv')}"""
    subprocess.run(command, shell=True)
    print("Checking processed habitat map alignment...")
    ###### Janky realignment code ######
    f = []
    for path, subdirs, files in os.walk(os.path.join("data", "habitat", "pnv")):
        for name in files:
            f.append(os.path.join(path, name))
    habitat_files = [_ for _ in f if "lcc_" in _ and ".tif" in _]
    for hab_file in habitat_files:
        realign_geotiff_origin(hab_file, tolerance=1E-6)
        print("done.")
    #######
else:
    print(f"AOH-processed PNV map exists - skipping creation")

# Generate an area scaling map
if not os.path.isfile(os.path.join('data', 'area-per-pixel.tif')):
    print("Generating area-per-pixel map...")
    command = f"""python3 ./prepare_layers/make_area_map.py --scale 0.083333333333333 --output {os.path.join("..", 'data', 'area-per-pixel.tif')}"""
    subprocess.run(command, cwd= os.path.join(os.getcwd(), 'LIFE'), shell=True)
    # realign_geotiff_origin(os.path.join('data', 'area-per-pixel.tif'), tolerance=1E-6, origin=(0, 90.0))
    print("done.")

# prepare the modified 'current' map
with open("data_index.json", 'r') as f:
    data_index = json.load(f)

update_findex = False
for year in years:
    # sum mapspam areas
    spam_year_file = os.path.join('data', 'food', "mapspam", f"mapspam_all_{year}.tif")
    if not os.path.isfile(spam_year_file) or overwrite:
        update_findex = True
        print(f"Summarising Mapspam layers for year {year}...", end=" ")
        _build_spam_layer.summarise_spam_layers(data_index.get(year, {}), year, spam_year_file)
        data_index[year]['mapspam_total_percentage'] = spam_year_file
        print("done.")
    else:
        print(f"Mapspam sum for year {year} exists - skipping creation")

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

    if not os.path.isfile(os.path.join(current_layers_dir, 'crop.tif')) or not os.path.isfile(os.path.join(current_layers_dir, 'pasture.tif')) or overwrite:
        print(f"Building GAEZ + HYDE layers for year {year}...", end=" ")
        # run this as a subprocess to avoid import problem
        command = f"""python3 ./prepare_layers/build_gaez_hyde.py --gaez {Path(os.path.join("..", 'data', 'food', "mapspam", f'mapspam_all_{year}.tif'))} \
                    --hyde {Path(os.path.join("..", 'data', 'food', 'hyde', f'modified_grazing{year}AD.asc'))} \
                    --output {Path(os.path.join("..", current_layers_dir))}"""
        subprocess.run(command, cwd = os.path.join(os.getcwd(), 'LIFE'),
                    shell=True)
        print("done.")
    else:
        print(f"crop.tif and pasture.tif layers for year {year} exist - skipping creation")

    # build diff rasters
    if not os.path.isfile(os.path.join(current_layers_dir, 'crop_diff.tif')) or not os.path.isfile(os.path.join(current_layers_dir, 'pasture_diff.tif')) or overwrite:
        print("Building difference rasters...")
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
        print("done.")
    else:
        print(f"Difference rasters for year {year} exist - skipping creation")
    
    # build food map
    if not os.path.isfile(os.path.join('data', 'food', f'current_raw_{year}.tif')) or overwrite:
        print(f"Building food map for year {year}...", end=" ")
        import LIFE.prepare_layers.make_food_current_map
        LIFE.prepare_layers.make_food_current_map.make_food_current_map(
            current_lvl1_path = Path(os.path.join('data', 'habitat', 'current_raw.tif')),
            pnv_path = Path(os.path.join("data", "inputs", "habitat", "pnv_raw.tif")),
            crop_adjustment_path = Path(os.path.join(current_layers_dir, 'crop_diff.tif')),
            pasture_adjustment_path = Path(os.path.join(current_layers_dir, 'pasture_diff.tif')),
            output_path = Path(os.path.join('data', 'food', f'current_raw_{year}.tif')),
            processes_count = int(multithread),
            random_seed=42
        )
        print("done.")
    else:
        print(f"Food map for year {year} exists - skipping creation")
    