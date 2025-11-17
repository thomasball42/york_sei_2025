"""Extract relevant data and create and index for files"""

import os
import zipfile
import json
from pathlib import Path
import subprocess
import _get_data

multithread = 16
overwrite = False
years = ["2000", "2005", "2010", "2020"] # hardcoding because I don't think these will change in the immediate future..

_get_data.get_data() # download data if not already present

# generate crosswalk
if not os.path.isfile('data/crosswalk.csv') or overwrite:
    print("Generating iucn/Jung crosswalk...", end = " ")
    import LIFE.prepare_layers.generate_crosswalk
    LIFE.prepare_layers.generate_crosswalk.generate_crosswalk('data/crosswalk.csv')
    print("done.")
else:
    print("iucn/Jung crosswalk exists - skipping creation")

with open("data_urls.json", 'r') as f:
        data_urls = json.load(f)

data_index = {} # create a list of files and paths

# create directories for intermediate and output data
for _ in ["food","habitat"]:
    if not os.path.isdir(os.path.join('data', _)):
        os.makedirs(os.path.join('data', _), exist_ok=True)

f = []
for path, subdirs, files in os.walk('data/inputs'):
    for name in files:
        f.append(os.path.join(path, name))

mapspam_files = [_ for _ in f if ("phys_area" in _ or "physical_area" in _ or "physical-area" in _) and ".geotiff" in _ and "mapspam" in _] # terrible 
hyde_files = [_ for _ in f if "hyde" in _ and "grazing" in _ and ".xml" not in _]

# extract mapspam files if not done already
if not os.path.isdir(os.path.join("data", "food", "mapspam")) or overwrite:
    print("Extracting mapspam files...")
    os.makedirs(os.path.join("data", "food", "mapspam"), exist_ok=True)
    for file in mapspam_files:
        with zipfile.ZipFile(file, 'r') as zip_ref:
            zip_ref.extractall(os.path.join("data", "food", "mapspam", os.path.basename(file).split(".zip")[0]))
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

    spam_year_files = [_ for _ in f if "_A.tif" in _ and str(year) in _ and ".xml" not in _] # filters for correct year and '_A', which is 'all'
    
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
    if not os.path.isfile(mod_path) or overwrite or True:
        if not os.path.isdir(os.path.join("data", "food", "hyde")):
            os.makedirs(os.path.join("data", "food", "hyde"), exist_ok=True)
        if os.path.isfile(hyde_year_path):
            subprocess.run(f"sed 's/0.0833333/0.08333333333333333/' {hyde_year_path} > {mod_path}", shell=True)
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
