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

# prepare the modified 'current' map
with open("data_index.json", 'r') as f:
    data_index = json.load(f)

for year in years:
    # sum mapspam areas
    if not os.path.isfile(os.path.join('data', 'food', f"mapspam_all_{year}.tif")):
        print(f"Summarising Mapspam layers for year {year}...", end=" ")
        _build_spam_layer.summarise_spam_layers(data_index.get(year, {}), year)
        print("done.")
    else:
        print(f"Mapspam summary for year {year} exists - skipping creation")
