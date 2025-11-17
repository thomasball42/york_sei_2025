"""Downloads required input data files from specified URLs (mapspami and hyde databases) 
and saves them to designated directories

Annoyingly gets all the data from dataverse every time at the moment (because the output files aren't named consistently)
TB 31st Oct 2025"""

import requests
import os
import json
from easyDataverse import Dataverse  # type: ignore
import zipfile
import subprocess

def get_data():

    def download_file(url, filename):
        try:
            print(f"Attempting to download from: {url}")
            with requests.get(url, stream=True, allow_redirects=True) as r:
                r.raise_for_status() 
                total_size = int(r.headers.get('content-length', 0))
                print(f"File size to download: {total_size / (1024 * 1024):.2f} MB")
                
                with open(filename, 'wb') as f:
                    print(f"Saving content to: {os.path.abspath(f.name)}")

                    for chunk in r.iter_content(chunk_size=8192):

                        if chunk: 
                            f.write(chunk)

        except requests.exceptions.RequestException as e:
            print(f"\n An error occurred during download: {e}")
            
        except Exception as e:
            print(f"\n An unexpected error occurred: {e}")

    with open('data_urls.json', 'r') as f:
        data_urls = json.load(f)

    for dataname, datasets in data_urls.items():
        fpath = os.path.join('data', 'inputs', dataname)
        if not os.path.isdir(fpath):
            os.makedirs(fpath)

        for dataset, info in datasets.items():
            url = info.get('url')
            filename = f"{dataname}_{dataset}"
            target_path = os.path.join(fpath, filename)

            if not os.path.isfile(target_path):

                if "dataverse" in url.lower():
                    if not os.path.isdir(target_path):
                        print(f"\n--- Downloading **{dataset}** ---")
                        # This gets the mapspam data
                        doi = info.get("doi")
                        version = info.get("version", "latest")

                        dataverse_api_token = "2e41a1d3-e588-4246-b5ee-3ddf073efbb1" # security is my middle name
                        dataverse = Dataverse("https://dataverse.harvard.edu/",
                            api_token = dataverse_api_token)

                        dataset = dataverse.load_dataset(
                            pid=doi,
                            version=version,
                            filedir=target_path,
                        )
                             
                elif url:
                    
                    # this gets the HYDE data and unzips it
                    download_file(url, target_path)
                    if os.path.isfile(target_path):
                        with zipfile.ZipFile(target_path, 'r') as zip_ref:
                            zip_ref.extractall(fpath)
            
                else:
                    print(f"\nError: Missing 'url' or 'doi' in data_urls.json file for **{dataset}**")#

    # get the base 'current' map - this is the same across all runs.
    if not os.path.isfile(os.path.join('data', 'habitat', 'jung_l2_raw.tif')):
        print("Downloading Jung habitat data from zenodo...")
        command = """reclaimer zenodo --zenodo_id 4058819 \
                                --filename iucn_habitatclassification_composite_lvl2_ver004.zip \
                                --extract \
                                --output data/habitat/jung_l2_raw.tif"""
        subprocess.run(command, shell = True)

    if not os.path.isdir(os.path.join('data', 'habitat', 'lvl2_changemasks_ver004')):
        print("Downloading Jung habitat change masks from zenodo...")
        command = """reclaimer zenodo --zenodo_id 4058819 \
                                --filename lvl2_changemasks_ver004.zip \
                                --extract \
                                --output data/habitat/"""
        subprocess.run(command, shell = True)

if __name__ == "__main__":
    get_data()