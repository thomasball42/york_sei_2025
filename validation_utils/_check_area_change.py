"""Check the total physical area (km2) that changes land-use under a scenario.

This is independent of species: it comes straight from the <scenario>_diff_area.tif
raster (built in 2_create_habitat_maps.py via LIFE/prepare_layers/make_diff_map.py),
where each pixel is (fraction of the pixel that changed between current and scenario)
* (pixel area in m^2). Summing it gives the actual physical land area converted by the
scenario -- a different quantity from _check_aggregate_value.py's per-species AOH
change (which is species-specific habitat area, not physical land area), which is why
it's checked here as a separate script.
"""

import csv
import logging
from pathlib import Path

from yirgacheffe.layers import RasterLayer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)

YEARS = ["2010", "2020"]
SCENARIO = "all_agri_to_pnv"
M2_PER_KM2 = 1_000_000.0

REPO_ROOT = Path(__file__).resolve().parent.parent
data_dirs_path = REPO_ROOT / "data" / "data_dirs"


def total_physical_area_change_km2(year_dir: Path, scenario: str) -> float:
    path = year_dir / f"{scenario}_diff_area.tif"
    if not path.exists():
        logger.warning("Diff-area raster not found at %s", path)
        return float("nan")
    with RasterLayer.layer_from_file(path) as layer:
        return layer.sum() / M2_PER_KM2


def main() -> None:
    output_path = data_dirs_path / "outputs" / "area_change_check.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for year in YEARS:
        year_dir = data_dirs_path / year
        area_km2 = total_physical_area_change_km2(year_dir, SCENARIO)
        logger.info("%s / %s: physical area changed = %.2f km2", year, SCENARIO, area_km2)
        rows.append({"year": year, "scenario": SCENARIO, "physical_area_change_km2": area_km2})

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["year", "scenario", "physical_area_change_km2"])
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Wrote %s", output_path)


if __name__ == "__main__":
    main()
