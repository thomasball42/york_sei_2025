"""Downloads required input data files from specified URLs (mapspam and hyde databases) 
and saves them to designated directories

Also gets GLW data for use in step 5.

Annoyingly gets all the data from dataverse every time at the moment (because the output files aren't named consistently)
TB 31st Oct 2025"""

import requests
import os
import json
from easyDataverse import Dataverse  # type: ignore
import zipfile
import subprocess

skip_spam = True

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

def get_data():

    with open('data_urls.json', 'r') as f:
        data_urls = json.load(f)

    if not skip_spam:
        for dataname, datasets in data_urls.items():
            fpath = os.path.join('data', 'inputs', dataname)
            if not os.path.isdir(fpath):
                os.makedirs(fpath)

            for dataset, info in datasets.items():
                url = info.get('url')
                filename = f"{dataname}_{dataset}"
                target_path = os.path.join(fpath, filename)

                if not os.path.isfile(target_path):
                    
                    dataverse_api_token = os.environ["DATAVERSE_API_TOKEN"]
                    
                    if "dataverse" in url.lower():
                        if not os.path.isdir(target_path):
                            print(f"\n--- Downloading **{dataset}** ---")
                            # This gets the mapspam data
                            doi = info.get("doi")
                            version = info.get("version", "latest")

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
    if not os.path.isfile(os.path.join('data', "inputs", 'habitat', 'jung_l2_raw.tif')):
        print("Downloading Jung habitat data from zenodo...")
        command = f"""reclaimer zenodo --zenodo_id 4058819 \
                    --filename iucn_habitatclassification_composite_lvl2_ver004.zip \
                    --extract \
                    --output {os.path.join('data', "inputs", 'habitat', 'jung_l2_raw.tif')}"""
        subprocess.run(command, shell = True)

    if not os.path.isdir(os.path.join('data', "inputs", 'habitat', 'lvl2_changemasks_ver004')):
        print("Downloading Jung habitat change masks from zenodo...")
        command = f"""reclaimer zenodo --zenodo_id 4058819 \
                    --filename lvl2_changemasks_ver004.zip \
                    --extract \
                    --output {os.path.join('data', "inputs", 'habitat')}"""
        subprocess.run(command, shell = True)

    # get the PNV map
    if not os.path.isfile(os.path.join('data', "inputs", 'habitat', 'pnv_raw.tif')):
        print("Downloading Jung potential natural vegetation data from zenodo...")
        command = f"""reclaimer zenodo --zenodo_id 4038749 \
                --filename pnv_lvl1_004.zip \
                --extract \
                --output {os.path.join('data', "inputs", 'habitat', 'pnv_raw.tif')} """
        subprocess.run(command, shell = True)

    if not os.path.isfile(os.path.join("data", "inputs", "elevation.tif")):
        print("Downloading elevation data from zenodo...")
        command = f"""reclaimer zenodo --zenodo_id 5719984 \
                    --filename dem-100m-esri54017.tif \
                    --output {os.path.join('data', "inputs", 'elevation.tif')}"""
        subprocess.run(command, shell = True, check =True)
        
    if not os.path.isfile(os.path.join("data", "inputs", "elevation-max.tif")) or not os.path.isfile(os.path.join("data", "inputs", "elevation-min.tif")):
        print("Generating max elevation map...")
        command = f"""gdalwarp -t_srs EPSG:4326 -tr 0.083333333333333 -0.083333333333333 -r max -co COMPRESS=LZW -wo NUM_THREADS=40 {os.path.join('data', "inputs", 'elevation.tif')} {os.path.join('data', "inputs", 'elevation-max.tif')}"""
        subprocess.run(command, shell = True)

        print("Generating min elevation map...")
        command = f"""gdalwarp -t_srs EPSG:4326 -tr 0.083333333333333 -0.083333333333333 -r min -co COMPRESS=LZW -wo NUM_THREADS=40 {os.path.join('data', "inputs", 'elevation.tif')} {os.path.join('data', "inputs", 'elevation-min.tif')}"""
        subprocess.run(command, shell = True)
    else:
        print("Elevation data already present - skipping download and processing")

    out_dir = os.path.join("data", "inputs", "livestock")
    if not os.path.isfile(os.path.join(out_dir, "LivestockMap.zip")) or not os.path.isfile(os.path.join(out_dir, "MapUncertainty.zip")):    
        os.makedirs(out_dir, exist_ok=True)

        url1 = "https://zenodo.org/records/17128483/files/LivestockMap.zip?download=1/LivestockMap.zip"
        # url2 = "https://zenodo.org/records/17128483/files/MapUncertainty.zip?download=1/MapUncertainty.zip"

        subprocess.run(["curl", "-L", "-o", os.path.join(out_dir, "LivestockMap.zip"), url1], check=True)
        subprocess.run(["unzip", "-o", os.path.join(out_dir, "LivestockMap.zip"), "-d", out_dir], check=True)

        # subprocess.run(["curl", "-L", "-o", os.path.join(out_dir, "MapUncertainty.zip"), url2], check=True)
        # subprocess.run(["unzip", "-o", os.path.join(out_dir, "MapUncertainty.zip"), "-d", out_dir], check=True)

        # clean up files - not sure why these are included in the repo...
        subprocess.run( f'rm {os.path.join(out_dir, "*", "._*.tif")}',
                        shell=True,
                        )
        subprocess.run( f'rm -r {os.path.join(out_dir, "__MACOSX")}',
                        shell=True,
                        )
    else:
        print("Livestock data already present - skipping download and processing")

if __name__ == "__main__":
    get_data()