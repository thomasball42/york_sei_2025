import json
import os
from pathlib import Path
import subprocess

import _persistencegenerator_mod
import LIFE.utils.raster_sum
import LIFE.utils.species_totals
import LIFE.deltap.delta_p_scaled

years = [   "2010", 
            # "2020"
            ]

multithread = 16
venv_path = "/maps/tsb42/plantation_life/venv"
CURVE = "0.25"

SCENARIOS = [
            ]

TAXA = ["AMPHIBIA", "AVES", "MAMMALIA", "REPTILIA"]

data_dirs_path = "data/data_dirs"

def main():

    with open("scenarios.json", 'r') as f:
        scenario_info = json.load(f)

    for scenario_name, scenario_info in scenario_info.items():
        SCENARIOS.append(scenario_name)
        
    for year in years:
        year_path = os.path.join(data_dirs_path, str(year))
        
        print("Generating persistence calculator batch file")
        _persistencegenerator_mod.species_generator(
            data_dir=Path(year_path),
            curve = CURVE,
            aohs_path=Path(os.path.join(year_path, "aohs")),
            output_csv_path=Path(os.path.join(year_path, "persistencebatch.csv")),
            scenarios=SCENARIOS,
            species_info_dir=Path(os.path.join("data", "inputs", "species-info"))
        )
    
        command =  f"""
                littlejohn -j {multithread} \
                -o {os.path.join(year_path, "persistencebatch.log")} \
                -c {os.path.join(year_path, "persistencebatch.csv")} \
                {os.path.join(venv_path, "bin", "python3")} \
                -- {os.path.join("LIFE", "deltap", "global_code_residents_pixel.py")}
                    """

        subprocess.run(command, shell = True, check=True)

        for scenario in SCENARIOS:
            
            sum_dir = os.path.join(year_path, "deltap_sum", scenario, CURVE)
            if not os.path.isdir(sum_dir):
                os.makedirs(sum_dir, exist_ok=True)
                
            for taxa in TAXA:

                print(f"Collating delta P results for {taxa}...")
                LIFE.utils.raster_sum.raster_sum(
                    images_dir=Path(os.path.join(year_path, "deltap", scenario, CURVE, taxa)),
                    output_filename=Path(os.path.join(sum_dir, f"{taxa}.tif")),
                    processes_count=multithread
                )
            
            print("Calculating species totals...")
            LIFE.utils.species_totals.species_totals(
                deltaps_path=Path(os.path.join(year_path, "deltap", scenario, CURVE)),
                output_path=Path(os.path.join(year_path, "deltap", scenario, CURVE, "totals.csv"))
            )

            print("Calculating scaled total delta P map...")
            if not os.path.isdir(os.path.join(year_path, "deltap_final")):
                os.makedirs(os.path.join(year_path, "deltap_final"), exist_ok=True)

            LIFE.deltap.delta_p_scaled.delta_p_scaled_area(
                input_path=Path(os.path.abspath(sum_dir)),
                diff_area_map_path=Path(os.path.join(year_path, f"{scenario}_diff_area.tif")),
                totals_path=Path(os.path.join(year_path, "deltap", scenario, CURVE, "totals.csv")),
                output_path=Path(os.path.join(year_path, "deltap_final", f"scaled_{scenario}_{CURVE}.tif"))
            )

if __name__ == "__main__":
    main()