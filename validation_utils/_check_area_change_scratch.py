"""Check the total physical area (km2) that changes land-use under a scenario.

Scratch-data counterpart to _check_area_change.py, pointed at mwd24's
/scratch/mwd24/lifedata instead of this project's own data_dirs. This is
independent of species: it comes straight from the <scenario>_diff_area.tif
raster, where each pixel is (fraction of the pixel that changed between
current and scenario) * (pixel area in m^2). Unlike the main data_dirs layout,
this scratch dataset keeps the diff-area raster under habitat/ rather than at
the dataset root, and there's a single dataset rather than a per-year one.
"""

import csv
import logging
from pathlib import Path

from yirgacheffe.layers import RasterLayer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path("/maps/mwd24/hybrid_life_correction_v3")
OUTPUT_DIR = Path("/maps/tsb42/andrew_yardstick/restore_all")
SCENARIO = "restore_all"

M2_PER_KM2 = 1_000_000.0


def total_physical_area_change_km2(data_dir: Path, scenario: str) -> float:
    path = data_dir / "habitat" / f"{scenario}_diff_area.tif"
    if not path.exists():
        logger.warning("Diff-area raster not found at %s", path)
        return float("nan")
    with RasterLayer.layer_from_file(path) as layer:
        return layer.sum() / M2_PER_KM2


def main() -> None:
    output_path = OUTPUT_DIR / "area_change_check.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    area_km2 = total_physical_area_change_km2(DATA_DIR, SCENARIO)
    logger.info("%s: physical area changed = %.2f km2", SCENARIO, area_km2)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["scenario", "physical_area_change_km2"])
        writer.writeheader()
        writer.writerow({"scenario": SCENARIO, "physical_area_change_km2": area_km2})

    logger.info("Wrote %s", output_path)


if __name__ == "__main__":
    main()
