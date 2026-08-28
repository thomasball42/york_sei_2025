"""Extract relevant data and create and index for files"""

import os
import zipfile
import json
from pathlib import Path
import subprocess
import argparse
import _get_data
import _get_species_data
import _get_country_boundaries

multithread = 16
overwrite = False
years = [
        "2010",
        "2020"
        ]
data_dirs_path = "data/data_dirs"


def main(data_dirs_path=data_dirs_path, skip_sp=False):
    # create directories for intermediate and output data
    for _ in ["food", "habitat", os.path.join("inputs", "habitat")]:
        if not os.path.isdir(os.path.join("data", _)):
            os.makedirs(os.path.join("data", _), exist_ok=True)

    for y in years:
        if not os.path.isdir(os.path.join(data_dirs_path, y)):
            os.makedirs(os.path.join(data_dirs_path, y), exist_ok=True)#

    # generate crosswalk
    if not os.path.isfile(os.path.join("data", "inputs", "crosswalk.csv")) or overwrite:
        print("Generating iucn/Jung crosswalks...", end=" ")
        import LIFE.prepare_layers.generate_crosswalk
        LIFE.prepare_layers.generate_crosswalk.generate_crosswalk(os.path.join("data", "inputs", "crosswalk.csv"))
        print("done.")
    else:
        print("iucn/Jung crosswalk exists - skipping creation")

    _get_data.get_data()  # download data if not already present
    if not skip_sp:
        _get_species_data.get_species_data()  # download species data if not already present
    else:
        print("Skipping species data stage (--skip-sp)")

    _get_country_boundaries.get_country_data()  # download country boundaries if not already present

    with open("data_urls.json", 'r') as f:
        data_urls = json.load(f)

    data_index = {}  # create a list of files and paths

    f = []
    for path, subdirs, files in os.walk('data/inputs'):
        for name in files:
            f.append(os.path.join(path, name))

    mapspam_files = [_ for _ in f if ("phys_area" in _ or "physical_area" in _ or "physical-area" in _) and ".geotiff" in _ and "mapspam" in _]  # terrible
    hyde_files = [_ for _ in f if "hyde" in _ and "grazing" in _ and ".xml" not in _]

    # unzip all the mapspam files
    mapspam_out_root = os.path.join("data", "food", "mapspam")
    os.makedirs(mapspam_out_root, exist_ok=True)
    print("Extracting mapspam files...")
    extracted_any = False

    for file in mapspam_files:
        out_dir = os.path.join(mapspam_out_root, os.path.basename(file).split(".zip")[0])

        if os.path.isdir(out_dir) and not overwrite:
            print(f"  {os.path.basename(file)} already extracted - skipping")
            continue

        os.makedirs(out_dir, exist_ok=True)
        with zipfile.ZipFile(file, "r") as zip_ref:
            zip_ref.extractall(out_dir)
        print(f"  extracted {os.path.basename(file)}")
        extracted_any = True

    if extracted_any:
        print("done.")
    else:
        print("Mapspam files already extracted - skipping extraction")


    # this is very clunky but the data sctructure differs between versions - looks at the now-extracted mapspam folder
    f = []
    for path, subdirs, files in os.walk(os.path.join("data", "food", "mapspam")):
        for name in files:
            f.append(os.path.join(path, name))

    # populate the data index (points to the files for each year / crop)
    for year in years:

        year_data = {}

        spam_year_files = [_ for _ in f if "_A.tif" in _ and str(year) in _ and ".xml" not in _]  # filters for correct year and '_A', which is 'all'

        spam_year_data = {
            f_name.split(".")[-2].split("_")[-2]: {
                "path": f_name,
                "unit": "harvested area in hectares / pixel"
            }
            for f_name in spam_year_files
        }

        hyde_year_path = next((fp for fp in hyde_files if str(year) in fp), None)
        mod_path = os.path.join('data', 'food', 'hyde', "modified_" + os.path.split(hyde_year_path)[1])

        # even though they have the same res it's not to the same precision, this sorts that..
        if not os.path.isfile(mod_path) or overwrite:
            if not os.path.isdir(os.path.join("data", "food", "hyde")):
                os.makedirs(os.path.join("data", "food", "hyde"), exist_ok=True)
            if os.path.isfile(hyde_year_path):
                subprocess.run(f"sed 's/0.0833333/0.083333333333333/' {hyde_year_path} > {mod_path}", shell=True)
                # subprocess.run(f"sed 's/0.0833333/0.083333000000000/' {hyde_year_path} > {mod_path}", shell=True)
            else:
                exit(f"Make sure to download and extract hyde data for year {year} first")
        else:
            print(f"Hyde data for year {year} exists - skipping creation")

        data_index[str(year)] = {
            "mapspam": spam_year_data,
            "hyde": {
                "pasture": {
                    "path": mod_path,
                    "unit": "grazing area in km2 / pixel"
                }
            }
        }

    with open("data_index.json", 'w') as f:
        data_index = json.dump(data_index, f, indent=4)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract relevant data and create an index for files.")
    parser.add_argument(
        "--skip-sp",
        action="store_true",
        help="Skip species data download stage (_get_species_data.get_species_data()).",
    )
    args = parser.parse_args()

    main(skip_sp=args.skip_sp)