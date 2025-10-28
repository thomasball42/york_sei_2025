import requests
import os
import json
from easyDataverse import Dataverse
import zipfile

dataverse_api_token = "2e41a1d3-e588-4246-b5ee-3ddf073efbb1" # security is my middle name
dataverse = Dataverse("https://dataverse.harvard.edu/",
                      api_token = dataverse_api_token)


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

with open('data_urls', 'r') as f:
    data_urls = json.load(f)


for dataname, datasets in data_urls.items():
    fpath = os.path.join('data', dataname)
    if not os.path.isdir(fpath):
        os.makedirs(fpath)

    for dataset, info in datasets.items():
        url = info.get('url')
        filename = f"{dataname}_{dataset}.zip"
        target_path = os.path.join(fpath, filename)
        
        if "dataverse" in url.lower():
            
            doi = info.get("doi")
            version = info.get("version", "latest")
            dataset = dataverse.load_dataset(
                pid=doi,
                version=version,
                filedir=target_path,
            )
            
            
        elif url:
            
            download_file(url, target_path)
    
            
        else:
            print(f"\n--- Skipping **{dataset}** - Missing 'url' or 'doi' in data_urls file. ---")

        if os.path.isfile(target_path):
            with zipfile.ZipFile(target_path, 'r') as zip_ref:
                zip_ref.extractall(fpath)