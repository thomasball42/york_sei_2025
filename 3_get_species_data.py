import os
import subprocess
from pathlib import Path

taxa = ["AMPHIBIA", "AVES", "MAMMALIA", "REPTILIA"]

def main():

    if os.getenv("DB_USER") is None or os.getenv("DB_PASSWORD") is None:
        exit("Missing credentials - you need to set DB_USER and DB_PASSWORD environment variables (best to ask Michael or Tom!)")

    print("Retrieving species info...")
    os.makedirs(os.path.join("data", "species-info"), exist_ok=True)

    for taxon in taxa:
        print(f"Retrieving species data for class {taxon}...")
        os.makedirs(os.path.join("data", "species-info", taxon), exist_ok=True)

        command = f"""python3 ./prepare_species/extract_species_psql.py --class "{taxon}" \
                                                            --output {os.path.join("..", "data", "inputs", "species-info", taxon)} \a
                                                            --projection "EPSG:4326"
                                                            """
        proc = subprocess.run(command, shell=True, cwd=os.path.join(os.getcwd(), "LIFE"))
        print(f"Done fetching species data for class {taxon}.")

if __name__ == "__main__":
    main()