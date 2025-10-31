"""Extract relevant data and create and index for files"""

import os
import zipfile
import json

years = ["2000", "2005", "2010", "2020"] # hardcoding because I don't think these will change in the immediate future..

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
if not os.path.isdir('data/inputs_processed') or True:
    os.makedirs('data/inputs_processed', exist_ok=True)
    
    for file in mapspam_files:
        with zipfile.ZipFile(file, 'r') as zip_ref:
            zip_ref.extractall(os.path.join("data/inputs_processed", "mapspam", os.path.basename(file).split(".zip")[0]))

# this is very clunky but the data sctructure differs between versions - looks at the now-extracted mapspam folder
f = []
for path, subdirs, files in os.walk('data/inputs_processed'):
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

    data_index[str(year)] = {
        "mapspam": spam_year_data,
        "hyde": {
            "pasture": {
                # Use next with a generator expression for concise finding
                "path": next((fp for fp in hyde_files if str(year) in fp), None),
                "unit": "grazing area in km2 / pixel"
            }
        }
    }

with open("data_index.json", 'w') as f:
        data_index = json.dump(data_index, f, indent=4)
