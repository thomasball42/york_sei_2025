import argparse
import os
import subprocess
from pathlib import Path
import LIFE.utils.speciesgenerator
import json

years = [   
            "2010", 
            # "2020"
            ]

multithread = 24
venv_path = "/maps/tsb42/york_sei_2026/venv"

SCENARIOS = [
            "current", "pnv",
            ]

data_dirs_path = "data/data_dirs"

def main():

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force overwrite/rerun even if outputs already exist"
    )
    args = parser.parse_args()

    with open("scenarios.json", 'r') as f:
        scenario_info = json.load(f)

    for scenario_name, scenario_info in scenario_info.items():
        SCENARIOS.append(scenario_name)

    for year in years:
        year_path = os.path.join(data_dirs_path, str(year))
        
        if args.force or not os.path.isdir(os.path.join(year_path, "aohs")):
            os.makedirs(os.path.join(year_path, "aohs"), exist_ok=True)
        
            # this is super quick so don't need to check if it's done
            print("Generating species aoh calc batch file")
            LIFE.utils.speciesgenerator.species_generator(
                data_dir=Path(os.path.join("data", "inputs")),
                output_csv_path=Path(os.path.join(year_path, "aohbatch.csv")),
                scenarios=SCENARIOS,
                habitats_path=Path(os.path.join(year_path, "habitat_maps")),
                aohs_path=Path(os.path.join(year_path, "aohs"))
            )   

            # run AOH calcs
            print("Calculating AOHs")
            command = f"""littlejohn \
                        -j {multithread} \
                        -o {os.path.join(year_path, "aohbatch.log")} \
                        -c {os.path.join(year_path, "aohbatch.csv")} {os.path.join(venv_path, "bin", "aoh-calc")} \
                        -- --force-habitat \
                        --pixel-area
                        """
            subprocess.run(command, shell = True, check = True)
            
            for _ in SCENARIOS:
                print(f"Collating results {_}...")
                command = f""" aoh-collate-data --aoh_results {os.path.join(year_path, "aohs", _)} \
                            --output {os.path.join(year_path, "aohs", f"{_}.csv")}
                            """
                subprocess.run(command, shell = True)
    
        if not os.path.isdir(os.path.join(year_path, "predictors")):
            os.makedirs(os.path.join(year_path, "predictors"), exist_ok=True)
            
        if not os.path.isfile(os.path.join(year_path, "predictors", "species_richness.tif")):
            print("Calculating species richness...")
            command = f"""aoh-species-richness --aohs_folder {os.path.join(year_path, "aohs", "current")} \
                        --output {os.path.join(year_path, "predictors", "species_richness.tif")}"""
            subprocess.run(command, shell = True)
        
        if not os.path.isfile(os.path.join(year_path, "predictors", "endemism.tif")):
            print("Calculating endemism...")
            command = f"""aoh-endemism --aohs_folder {os.path.join(year_path, "aohs", "current")} \
                        --species_richness {os.path.join(year_path, "predictors", "species_richness.tif")}\
                        --output {os.path.join(year_path, "predictors", "endemism.tif")}"""
            subprocess.run(command, shell = True)
        
if __name__=="__main__":
    main()