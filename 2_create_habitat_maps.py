"""creates habitat map for year of interest"""

import json
import subprocess
import os
from pathlib import Path
import _build_spam_layer
from _gdal_aligner import realign_geotiff_origin
from osgeo import gdal

gdal.SetCacheMax(5 * 1024 * 1024 * 1024)

# years = ["2000", "2005", "2010", "2020"]
# years = ["2000"]
years = ["2005", "2010", "2020"]

multithread = 16
overwrite = False

# check if hab map exists
if not os.path.isfile(os.path.join('data', 'habitat', "current", f'current_raw.tif')) or overwrite:
    print(f"Creating habitat map from Jung data...")
    import LIFE.prepare_layers.make_current_map
    LIFE.prepare_layers.make_current_map.make_current_map(
        jung_path = Path(os.path.join('data', 'inputs', 'habitat', 'jung_l2_raw.tif')),
        update_masks_path = None,
        crosswalk_path = Path(os.path.join('data', "inputs", 'crosswalk.csv')),
        output_path = Path(os.path.join('data', 'habitat', "current", 'current_raw.tif')),
        concurrency = int(multithread),
        show_progress = True,
    )
else:
    print(f"Jung base habitat map exists - skipping creation")

# process current habitat map - this is needed to build the food map later
if not os.path.isfile(os.path.join('data', 'habitat', "current", 'lcc_1401.tif')) or not os.path.isfile(os.path.join('data', 'habitat', "current", 'lcc_1402.tif')) or overwrite:
    print(f"Running some aoh-processing..")
    command = f"""aoh-habitat-process --habitat {os.path.join('data', 'habitat', "current",'current_raw.tif')} \
                --scale 0.083333333333333 \
                --output {os.path.join('data', 'habitat', "current")}"""
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

# process pnv habitat map 
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

else:
    print(f"AOH-processed PNV map exists - skipping creation")

# Generate an area scaling map
if not os.path.isfile(os.path.join('data', "inputs", 'area-per-pixel.tif')) or overwrite:
    print("Generating area-per-pixel map...")
    command = f"""python3 ./prepare_layers/make_area_map.py --scale 0.083333333333333 --output {os.path.join("..", 'data', "inputs", 'area-per-pixel.tif')}"""
    subprocess.run(command, cwd= os.path.join(os.getcwd(), 'LIFE'), shell=True)
    print("done.")

# prepare the modified 'current' map
with open("data_index.json", 'r') as f:
    data_index = json.load(f)

for year in years:
    
    # construct the mapspam summed layer
    spam_year_file = os.path.join('data', 'food', "mapspam", f"mapspam_all_{year}.tif")
    if not os.path.isfile(spam_year_file) or overwrite:
        update_findex = True
        print(f"Summarising Mapspam layers for year {year}...", end=" ")
        _build_spam_layer.summarise_spam_layers(data_index.get(year, {}), year, spam_year_file)
        data_index[year]['mapspam_total_percentage'] = spam_year_file
        print("done.")
    else:
        print(f"Mapspam sum for year {year} exists - skipping creation")

    # check hyde projection exists
    hyde_prj_path = os.path.join('data', 'food', 'hyde', f'modified_grazing{year}AD.prj') 
    command = f"""echo 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AXIS["Latitude",NORTH],AXIS["Longitude",EAST],AUTHORITY["EPSG","4326"]]' > {hyde_prj_path}"""
    subprocess.run(command, shell=True)




    # set up directories for scenarios
    year_dir = os.path.join('data', 'data_dirs', year)
    hab_maps_dir = os.path.join(year_dir, "habitat_maps")
    current_dir = os.path.join(hab_maps_dir, 'current')
    pnv_dir = os.path.join(hab_maps_dir, 'pnv')
    scenario_dir = os.path.join(hab_maps_dir, 'restore_agriculture')

    food_processing_dir = os.path.join(year_dir, "food_processing")

    dirs = [year_dir, current_dir, pnv_dir, scenario_dir, food_processing_dir]
    for dir in dirs:
        if not os.path.isdir(dir):
            os.makedirs(dir, exist_ok=True)

    if not os.path.isfile(os.path.join(pnv_dir, "lcc_100.tif")) or overwrite:
        print(f"Copying processed PNV map to data dir for year {year}...")
        command = f"""cp {os.path.join('data', 'habitat', 'pnv', "*")} {os.path.join(pnv_dir)}"""
        subprocess.run(command, shell=True)
        print("done.")


    if not os.path.isfile(os.path.join(current_dir, 'crop.tif')) or not os.path.isfile(os.path.join(current_dir, 'pasture.tif')) or overwrite:
        print(f"Building GAEZ + HYDE layers for year {year}...", end=" ")
        # run this as a subprocess to avoid import problem
        command = f"""python3 ./prepare_layers/build_gaez_hyde.py --gaez {Path(os.path.join("..", 'data', 'food', "mapspam", f'mapspam_all_{year}.tif'))} \
                    --hyde {Path(os.path.join("..", 'data', 'food', 'hyde', f'modified_grazing{year}AD.asc'))} \
                    --output {Path(os.path.join("..", food_processing_dir))}"""
        subprocess.run(command, cwd = os.path.join(os.getcwd(), 'LIFE'),
                    shell=True)
        print("done.")
    else:
        print(f"crop.tif and pasture.tif layers for year {year} exist - skipping creation")

    # build diff rasters
    if not os.path.isfile(os.path.join(food_processing_dir, 'crop_diff.tif')) or not os.path.isfile(os.path.join(food_processing_dir, 'pasture_diff.tif')) or overwrite:
        print("Building difference rasters...")
        import LIFE.utils.raster_diff
        LIFE.utils.raster_diff.raster_diff(
            raster_a_path = Path(os.path.join(food_processing_dir, 'crop.tif')),
            raster_b_path = Path(os.path.join('data', 'habitat', "current", 'lcc_1401.tif')),
            output_path = Path(os.path.join(food_processing_dir, 'crop_diff.tif')),
        )
        LIFE.utils.raster_diff.raster_diff(
            raster_a_path = Path(os.path.join(food_processing_dir, 'pasture.tif')),
            raster_b_path = Path(os.path.join('data', 'habitat', "current", 'lcc_1402.tif')),
            output_path = Path(os.path.join(food_processing_dir, 'pasture_diff.tif')),
        )
        print("done.")
    else:
        print(f"Difference rasters for year {year} exist - skipping creation")
    
    # build food map
    if not os.path.isfile(os.path.join(year_dir, f'current_raw.tif')) or overwrite:
        print(f"Building food map for year {year}...", end=" ")
        import LIFE.prepare_layers.make_food_current_map
        LIFE.prepare_layers.make_food_current_map.make_food_current_map(
            current_lvl1_path = Path(os.path.join('data', 'habitat', "current", 'current_raw.tif')),
            pnv_path = Path(os.path.join("data", "inputs", "habitat", "pnv_raw.tif")),
            crop_adjustment_path = Path(os.path.join(food_processing_dir, 'crop_diff.tif')),
            pasture_adjustment_path = Path(os.path.join(food_processing_dir, 'pasture_diff.tif')),
            output_path = Path(os.path.join(year_dir, f'current_raw.tif')),
            processes_count = int(multithread),
            random_seed=42
        )
        print("done.")
    else:
        print(f"Food map for year {year} exists - skipping creation")

    if not os.path.isfile(os.path.join(current_dir, "lcc_1401.tif")) or overwrite:
        print(f"Running AOH processing on restoration habitat map for year {year}...")
        command = f"""aoh-habitat-process --habitat {os.path.join(year_dir, 'current_raw.tif')} \
                    --scale 0.083333333333333 \
                    --output {current_dir}"""
        subprocess.run(command, shell=True)
        print("done.")


    # build restoration map
    if os.path.isfile(os.path.join(current_dir, f'restore_agriculture.tif')) or overwrite:
        print(f"Restoration habitat map exists - skipping creation")
    else:
        print(f"Creating restoration habitat map for year {year}...")
        import LIFE.prepare_layers.make_restore_agriculture_map
        LIFE.prepare_layers.make_restore_agriculture_map.make_restore_map(
            pnv_path = Path(os.path.join('data', 'inputs', 'habitat', 'pnv_raw.tif')),
            current_path = Path(os.path.join(year_dir, 'current_raw.tif')),
            crosswalk_path = Path(os.path.join('data', "inputs", 'crosswalk.csv')),
            output_path = Path(os.path.join(year_dir, 'restore_agriculture.tif')),
            concurrency = int(multithread),
            show_progress=True,
        )
        print("done.")

    if not os.path.isfile(os.path.join(scenario_dir, "lcc_100.tif")) or overwrite:
        print(f"Running AOH processing on restoration habitat map for year {year}...")
        command = f"""aoh-habitat-process --habitat {os.path.join(year_dir, 'restore_agriculture.tif')} \
                    --scale 0.083333333333333 \
                    --output {scenario_dir}"""
        subprocess.run(command, shell=True)
        print("done.")
    else:
        print(f"AOH-processed restoration habitat map for year {year} exists - skipping creation")

    if not os.path.isfile(os.path.join(year_dir, "restore_agriculture_diff_area.tif")) or overwrite:
        print(f"Creating restoration habitat difference map for year {year}...")
        import LIFE.prepare_layers.make_diff_map
        LIFE.prepare_layers.make_diff_map.make_diff_map(
            current_path = Path(os.path.join(year_dir, 'current_raw.tif')),
            scenario_path = Path(os.path.join(year_dir, 'restore_agriculture.tif')),
            area_path = Path(os.path.join('data', "inputs", 'area-per-pixel.tif')),
            pixel_scale = 0.083333333333333,
            output_path = Path(os.path.join(year_dir, 'restore_agriculture_diff_area.tif')),
            target_projection=None,
            concurrency = int(multithread),
            show_progress=True
        )
        print("done.")
    else:   
        print(f"Restoration habitat difference map for year {year} exists - skipping creation")
