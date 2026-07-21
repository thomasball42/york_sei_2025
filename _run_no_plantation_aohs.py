import csv
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
YEAR = "2010"
YEAR_PATH = DATA_DIR / "data_dirs" / YEAR
SPECIES_INFO_DIR = DATA_DIR / "inputs" / "species-info"
CROSSWALK_PATH = DATA_DIR / "inputs" / "crosswalk.csv"
CROSSWALK_NOPL_PATH = DATA_DIR / "inputs" / "crosswalk_nopl.csv"
PLANTATION_VALUE = "1403"
SUFFIX = "_nopl_aohmod"

TAXAS = ["MAMMALIA", "AVES", "REPTILIA", "AMPHIBIA"]

multithread = 24
venv_path = "/maps/tsb42/plantation_life/venv"

HABITAT_CODE_RE = re.compile(r'"full_habitat_code"\s*:\s*"([^"]*)"')
FILENAME_RE = re.compile(r"^(\d+)_(\w+)\.geojson$")
OUTPUT_FILENAME_RE = re.compile(r"^aoh_T(\d+)A\d+_(\w+)\.")


def build_crosswalk_nopl():
    with open(CROSSWALK_PATH, newline="") as f:
        rows = list(csv.reader(f))
    header, body = rows[0], rows[1:]
    kept = [row for row in body if row[1] != PLANTATION_VALUE]
    dropped = len(body) - len(kept)
    with open(CROSSWALK_NOPL_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(kept)
    print(f"Wrote {CROSSWALK_NOPL_PATH} ({dropped} plantation rows dropped, {len(kept)} rows kept)")


def species_favours_plantation(geojson_path: Path) -> bool:
    text = geojson_path.read_text()
    m = HABITAT_CODE_RE.search(text)
    if not m:
        return False
    codes = m.group(1).split("|")
    return "14" in codes or "14.3" in codes


def get_species_files():
    """Returns list of (taxa, id_no, season, geojson_path)."""
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
    """Scan a taxa output dir once, building {(id_no, season): [filenames]}."""
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
    scenarios = list(scenario_info.keys())
    print(f"Scenarios: {scenarios}")

    build_crosswalk_nopl()

    species_files = get_species_files()
    print(f"Total species-season files: {len(species_files)}")

    affected = []
    unaffected = []
    for s in species_files:
        (affected if species_favours_plantation(s[3]) else unaffected).append(s)
    print(f"Affected (plantation-favouring) species-season files: {len(affected)}")
    print(f"Unaffected species-season files: {len(unaffected)}")

    habitats_root = YEAR_PATH / "habitat_maps"
    aohs_root = YEAR_PATH / "aohs"

    batch_rows = []

    unaffected_by_taxa = {}
    for taxa, id_no, season, _ in unaffected:
        unaffected_by_taxa.setdefault(taxa, []).append((id_no, season))

    for scenario in scenarios:
        new_scenario_dir = aohs_root / f"{scenario}{SUFFIX}"
        old_scenario_dir = aohs_root / scenario
        for taxa in TAXAS:
            (new_scenario_dir / taxa).mkdir(parents=True, exist_ok=True)

        # Hardlink/copy unaffected species outputs from the existing run.
        linked = 0
        for taxa in TAXAS:
            old_taxa_dir = old_scenario_dir / taxa
            new_taxa_dir = new_scenario_dir / taxa
            output_index = index_outputs_by_id_season(old_taxa_dir)
            for id_no, season in unaffected_by_taxa.get(taxa, []):
                for filename in output_index.get((id_no, season), []):
                    src = old_taxa_dir / filename
                    dst = new_taxa_dir / filename
                    if not dst.exists():
                        link_or_copy(src, dst)
                        linked += 1
        print(f"[{scenario}] linked/copied {linked} files for unaffected species")

        # Queue affected species for recomputation with the plantation-free crosswalk.
        habitat_maps_path = habitats_root / scenario
        for taxa, id_no, season, geojson_path in affected:
            batch_rows.append([
                habitat_maps_path,
                DATA_DIR / "inputs" / "elevation-max.tif",
                DATA_DIR / "inputs" / "elevation-min.tif",
                CROSSWALK_NOPL_PATH,
                geojson_path,
                new_scenario_dir / taxa,
            ])

    batch_csv_path = YEAR_PATH / "aohbatch_nopl.csv"
    with open(batch_csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "--fractional_habitats", "--elevation-max", "--elevation-min",
            "--crosswalk", "--speciesdata", "--output",
        ])
        writer.writerows(batch_rows)
    print(f"Wrote {batch_csv_path} with {len(batch_rows)} rows to (re)compute")

    print("Calculating AOHs for plantation-favouring species (no-plantation-credit crosswalk)...")
    command = f"""littlejohn \
                -j {multithread} \
                -o {YEAR_PATH / "aohbatch_nopl.log"} \
                -c {batch_csv_path} {os.path.join(venv_path, "bin", "aoh-calc")} \
                -- --force-habitat \
                --pixel-area
                """
    subprocess.run(command, shell=True, check=True)

    predictors_dir = YEAR_PATH / "predictors"
    predictors_dir.mkdir(parents=True, exist_ok=True)

    for scenario in scenarios:
        new_scenario_dir = aohs_root / f"{scenario}{SUFFIX}"
        print(f"Collating results {scenario}{SUFFIX}...")
        command = f"""aoh-collate-data --aoh_results {new_scenario_dir} \
                    --output {aohs_root / f"{scenario}{SUFFIX}.csv"}
                    """
        subprocess.run(command, shell=True, check=True)

        print(f"Calculating predictors for {scenario}{SUFFIX}...")
        richness_path = predictors_dir / f"{scenario}{SUFFIX}_species_richness.tif"
        command = f"""aoh-species-richness --aohs_folder {new_scenario_dir} \
                    --output {richness_path}"""
        subprocess.run(command, shell=True, check=True)

        command = f"""aoh-endemism --aohs_folder {new_scenario_dir} \
                    --species_richness {richness_path} \
                    --output {predictors_dir / f"{scenario}{SUFFIX}_endemism.tif"}"""
        subprocess.run(command, shell=True, check=True)


if __name__ == "__main__":
    main()
