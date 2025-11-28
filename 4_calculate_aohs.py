import os
import subprocess
from pathlib import Path

results_path = os.path.join("data", "results")
# years = ["2000", "2005", "2010", "2020"]
years = ["2000"]
SCENARIOS = ["current", "pnv", "restore_agriculture"]
CURVE = "0.25"
multithread = 24
venv_path = "/maps/tsb42/york_sei_2025/env/"
def main():

    import LIFE.utils.speciesgenerator
    import LIFE.utils.persistencegenerator

    for year in years:
        year_path = os.path.join("data", "data_dirs", str(year))

        if os.path.isdir(os.path.join(year_path, "aohs")):
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
        
        print("Generating persistence calculator batch file")
        LIFE.utils.persistencegenerator.species_generator(
            data_dir=Path(os.path.join("data", "inputs")),
            aohs_path=Path(os.path.join(year_path, "aohs")),
            curve = CURVE,
            output_csv_path=Path(os.path.join(year_path, "persistencebatch.csv")),
            scenarios=SCENARIOS
        )

        # run AOH calcs
        print("Calculating AOHs")
        command = f"""littlejohn \
                    -j {multithread} \
                    -o {os.path.join(year_path, "aohbatch.log")} \
                    -c {os.path.join(year_path, "aohbatch.csv")} {os.path.join(venv_path, "bin", "aoh-calc")} \
                    -- --force-habitat
                    """
        subprocess.run(command, shell = True)
        
        for _ in ["pnv", "current", "restore_agriculture"]:
            print(f"Collating results {_}...")
            command = f""" aoh-collate-data --aoh_results {os.path.join(year_path, "aohs", _)} \
                        --output {os.path.join(year_path, "aohs", f"{_}.csv")}
                        """
            subprocess.run(command, shell = True)
        
        if os.path.isdir(os.path.join(year_path, "predictors")):
            os.makedirs(os.path.join(year_path, "predictors"), exist_ok=True)
        
        print("Calculating predictors for analysis...")
        command = f"""aoh-species-richness --aohs_folder {os.path.join(year_path, "aohs", "current")} \
                     --output {os.path.join(year_path, "predictors", "species_richness.tif")}"""
        subprocess.run(command, shell = True)
        
        command = f"""aoh-endemism --aohs_folder {os.path.join(year_path, "aohs", "current")} \
                    --species_richness {os.path.join(year_path, "predictors", "species_richness.tif")}\
                    --output {os.path.join(year_path, "predictors", "endemism.tif")}"""
        subprocess.run(command, shell = True)
        
if __name__=="__main__":
    main()