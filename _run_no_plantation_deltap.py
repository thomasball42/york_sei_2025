import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pandas as pd

import LIFE.utils.raster_sum
import LIFE.utils.species_totals
import LIFE.deltap.delta_p_scaled

BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
YEAR = "2010"
YEAR_PATH = DATA_DIR / "data_dirs" / YEAR
SPECIES_INFO_DIR = DATA_DIR / "inputs" / "species-info"
SUFFIX = "_nopl_aohmod"
CURVE = "0.25"

TAXAS = ["AMPHIBIA", "AVES", "MAMMALIA", "REPTILIA"]

multithread = 16
venv_path = "/maps/tsb42/plantation_life/venv"

HABITAT_CODE_RE = re.compile(r'"full_habitat_code"\s*:\s*"([^"]*)"')
FILENAME_RE = re.compile(r"^(\d+)_(\w+)\.geojson$")
OUTPUT_FILENAME_RE = re.compile(r"^aoh_T(\d+)A\d+_(\w+)\.")


def species_favours_plantation(geojson_path: Path) -> bool:
    text = geojson_path.read_text()
    m = HABITAT_CODE_RE.search(text)
    if not m:
        return False
    codes = m.group(1).split("|")
    return "14" in codes or "14.3" in codes


def get_species_files():
    res = []
    for taxa in TAXAS:
        taxa_dir = SPECIES_INFO_DIR / taxa / "current"
        for geojson_path in taxa_dir.glob("*.geojson"):
            m = FILENAME_RE.match(geojson_path.name)
            if not m:
                raise ValueError(f"Unexpected filename format: {geojson_path}")
            id_no, season = m.groups()
            res.append((taxa, id_no, season, geojson_path))
    return res


def link_or_copy(src: Path, dst: Path):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def index_outputs_by_id_season(taxa_dir: Path):
    index = {}
    if not taxa_dir.is_dir():
        return index
    for entry in os.scandir(taxa_dir):
        m = OUTPUT_FILENAME_RE.match(entry.name)
        if not m:
            continue
        key = m.groups()
        index.setdefault(key, []).append(entry.name)
    return index


def main():
    with open(BASE / "scenarios.json", "r") as f:
        scenario_info = json.load(f)
    base_scenarios = list(scenario_info.keys())
    print(f"Base scenarios: {base_scenarios}")

    species_files = get_species_files()
    affected = []
    unaffected = []
    for s in species_files:
        (affected if species_favours_plantation(s[3]) else unaffected).append(s)
    print(f"Affected species-season files: {len(affected)}")
    print(f"Unaffected species-season files: {len(unaffected)}")

    unaffected_by_taxa = {}
    for taxa, id_no, season, _ in unaffected:
        unaffected_by_taxa.setdefault(taxa, []).append((id_no, season))

    aohs_path = YEAR_PATH / "aohs"
    current_aoh_dir = aohs_path / f"current{SUFFIX}"
    historic_aoh_dir = aohs_path / "pnv"

    batch_rows = []

    for base_scenario in base_scenarios:
        new_scenario = f"{base_scenario}{SUFFIX}"
        scenario_aoh_dir = aohs_path / new_scenario

        old_deltap_dir = YEAR_PATH / "deltap" / base_scenario / CURVE
        new_deltap_dir = YEAR_PATH / "deltap" / new_scenario / CURVE
        for taxa in TAXAS:
            (new_deltap_dir / taxa).mkdir(parents=True, exist_ok=True)

        # Hardlink/copy unaffected species' existing delta-P outputs - since both the
        # current and scenario AOH inputs are byte-identical to the original run for
        # these species, the delta-P result is guaranteed identical too.
        linked = 0
        for taxa in TAXAS:
            old_taxa_dir = old_deltap_dir / taxa
            new_taxa_dir = new_deltap_dir / taxa
            output_index = index_outputs_by_id_season(old_taxa_dir)
            for id_no, season in unaffected_by_taxa.get(taxa, []):
                for filename in output_index.get((id_no, season), []):
                    src = old_taxa_dir / filename
                    dst = new_taxa_dir / filename
                    if not dst.exists():
                        link_or_copy(src, dst)
                        linked += 1
        print(f"[{new_scenario}] linked/copied {linked} delta-P files for unaffected species")

        for taxa, id_no, season, geojson_path in affected:
            batch_rows.append([
                geojson_path,
                current_aoh_dir / taxa,
                scenario_aoh_dir / taxa,
                historic_aoh_dir / taxa,
                CURVE,
                new_deltap_dir / taxa,
            ])

    df = pd.DataFrame(batch_rows, columns=[
        '--speciesdata', '--current_path', '--scenario_path',
        '--historic_path', '--z', '--output_path',
    ])
    batch_csv_path = YEAR_PATH / "persistencebatch_nopl.csv"
    df.to_csv(batch_csv_path, index=False)
    print(f"Wrote {batch_csv_path} with {len(df)} rows to (re)compute")

    command = f"""
            littlejohn -j {multithread} \
            -o {YEAR_PATH / "persistencebatch_nopl.log"} \
            -c {batch_csv_path} \
            {os.path.join(venv_path, "bin", "python3")} \
            -- {os.path.join("LIFE", "deltap", "global_code_residents_pixel.py")}
                """
    subprocess.run(command, shell=True, check=True)

    for base_scenario in base_scenarios:
        new_scenario = f"{base_scenario}{SUFFIX}"
        sum_dir = YEAR_PATH / "deltap_sum" / new_scenario / CURVE
        sum_dir.mkdir(parents=True, exist_ok=True)

        for taxa in TAXAS:
            print(f"Collating delta P results for {taxa} ({new_scenario})...")
            LIFE.utils.raster_sum.raster_sum(
                images_dir=YEAR_PATH / "deltap" / new_scenario / CURVE / taxa,
                output_filename=sum_dir / f"{taxa}.tif",
                processes_count=multithread,
            )

        print(f"Calculating species totals ({new_scenario})...")
        LIFE.utils.species_totals.species_totals(
            deltaps_path=YEAR_PATH / "deltap" / new_scenario / CURVE,
            output_path=YEAR_PATH / "deltap" / new_scenario / CURVE / "totals.csv",
        )

        print(f"Calculating scaled total delta P map ({new_scenario})...")
        (YEAR_PATH / "deltap_final").mkdir(parents=True, exist_ok=True)
        LIFE.deltap.delta_p_scaled.delta_p_scaled_area(
            input_path=Path(os.path.abspath(sum_dir)),
            diff_area_map_path=YEAR_PATH / f"{base_scenario}_diff_area.tif",
            totals_path=YEAR_PATH / "deltap" / new_scenario / CURVE / "totals.csv",
            output_path=YEAR_PATH / "deltap_final" / f"scaled_{new_scenario}_{CURVE}.tif",
        )


if __name__ == "__main__":
    main()
