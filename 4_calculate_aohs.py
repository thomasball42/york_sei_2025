import os
import subprocess
from pathlib import Path

results_path = os.path.join("data", "results")
years = ["2000", "2005", "2010", "2020"]
scenarios = ["current", "pnv", "restore_agriculture"]
curve = "CURVE:0.25"

def main():

    import LIFE.utils.speciesgenerator

    for year in years:
        year_path = os.path.join("data", "data_dirs", str(year))

        LIFE.utils.speciesgenerator.species_generator(
            data_dir=Path(os.path.join("data", "inputs")),
            output_csv_path=Path(os.path.join(year_path, "aohbatch.csv")),
            scenarios=scenarios,
            habitats_path=Path(os.path.join(year_path, "habitat_maps")),
            aohs_path=Path(os.path.join("data", "species-info"))
        )