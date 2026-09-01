"""Check delta-p computed for a whole land-use change at once against the
per-pixel marginal-swap approach used by 4_calculate_deltap.py.

4_calculate_deltap.py computes, for each species and each pixel, the change in
persistence that would result from swapping just that one pixel from its
"current" value to its "scenario" value while holding every other pixel fixed,
then sums those per-pixel marginal changes across the whole raster. Because the
persistence curve (x**0.25) is non-linear, that sum-of-marginals is only an
approximation of what actually happens when every changed pixel is swapped
simultaneously. This script computes the real, non-approximated delta-p for
each species directly from its actual current-AOH and scenario-AOH totals (the
AOH rasters produced by 3_calculate_aohs.py already do the heavy lifting), and
reports it next to the existing pixel-summed totals so the size of the
linearization error is visible.
"""

import csv
import logging
import os
import resource
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from aoh import IUCNFormatFilename
from yirgacheffe.layers import RasterLayer

from LIFE.deltap.global_code_residents_pixel import calc_persistence_value

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)

YEARS = ["2010", "2020"]
SCENARIO = "all_agri_to_pnv"
CURVE = "0.25"
EXP_VAL = 0.25
TAXA = ["AMPHIBIA", "AVES", "MAMMALIA", "REPTILIA"]
NUM_THREADS = 48
EXCL_NEGS = True

data_dirs_path = "data/data_dirs"
species_info_path = os.path.join("data", "inputs", "species-info")

exponent_func = lambda x: x ** EXP_VAL  # pylint: disable=unnecessary-lambda-assignment


@dataclass
class WorkItem:
    taxa: str
    taxon_id: int
    assessment_id: Optional[int]
    season: str  # "RESIDENT" or "BREEDING+NONBREEDING"
    paths: dict = field(default_factory=dict)  # season label -> current-AOH Path


@dataclass
class ResultRow:
    taxa: str
    taxon_id: int
    assessment_id: Optional[int]
    season: str
    old_persistence: float
    new_persistence: float
    aggregate_delta_p: float
    current_aoh: Optional[float] = None
    historic_aoh: Optional[float] = None
    scenario_aoh: Optional[float] = None
    current_aoh_breeding: Optional[float] = None
    current_aoh_nonbreeding: Optional[float] = None
    historic_aoh_breeding: Optional[float] = None
    historic_aoh_nonbreeding: Optional[float] = None
    scenario_aoh_breeding: Optional[float] = None
    scenario_aoh_nonbreeding: Optional[float] = None


@dataclass
class SkipRow:
    taxa: str
    taxon_id: Optional[int]
    assessment_id: Optional[int]
    season: Optional[str]
    reason: str


PER_SPECIES_COLUMNS = [
    "taxa", "taxon_id", "assessment_id", "season",
    "current_aoh", "historic_aoh", "scenario_aoh",
    "current_aoh_breeding", "current_aoh_nonbreeding",
    "historic_aoh_breeding", "historic_aoh_nonbreeding",
    "scenario_aoh_breeding", "scenario_aoh_nonbreeding",
    "old_persistence", "new_persistence", "aggregate_delta_p",
]
SKIPPED_COLUMNS = ["taxa", "taxon_id", "assessment_id", "season", "reason"]
SUMMARY_COLUMNS = ["taxa", "species_count", "skipped_count", "aggregate_total", "pixel_total", "difference"]


def build_worklist(taxa: str, current_dir: Path, species_info_dir: Path) -> tuple[list[WorkItem], list[SkipRow]]:
    """Driving species list comes from species-info/<taxa>/current (matching
    _persistencegenerator_mod.py), resolved against the current AOH rasters that
    actually exist. AOH tif filenames are identical across scenario/pnv/current
    directories, so historic/scenario paths are derived by filename reuse rather
    than a per-species search."""

    current_index: dict[tuple[int, str], Path] = {}
    for path in current_dir.glob("*.tif"):
        try:
            parts = IUCNFormatFilename.of_filename(path)
        except ValueError:
            continue
        current_index[(parts.taxon_id, parts.season)] = path

    driving_groups: dict[int, dict[str, int]] = {}
    for path in species_info_dir.glob("*.geojson"):
        try:
            taxon_id_str, season = path.stem.rsplit("_", 1)
            taxon_id = int(taxon_id_str)
        except ValueError:
            logger.warning("Could not parse species-info filename %s, skipping", path)
            continue
        driving_groups.setdefault(taxon_id, {})[season] = taxon_id

    worklist: list[WorkItem] = []
    skips: list[SkipRow] = []

    for taxon_id, seasons in driving_groups.items():
        season_set = set(seasons.keys())

        if season_set == {"RESIDENT"}:
            current_path = current_index.get((taxon_id, "RESIDENT"))
            if current_path is None:
                skips.append(SkipRow(taxa, taxon_id, None, "RESIDENT", "missing current AOH (not found in aohs/current)"))
                continue
            assessment_id = IUCNFormatFilename.of_filename(current_path).assessment_id
            worklist.append(WorkItem(taxa, taxon_id, assessment_id, "RESIDENT", {"RESIDENT": current_path}))

        elif season_set == {"BREEDING", "NONBREEDING"}:
            breeding_path = current_index.get((taxon_id, "BREEDING"))
            nonbreeding_path = current_index.get((taxon_id, "NONBREEDING"))
            if breeding_path is None or nonbreeding_path is None:
                missing = "BREEDING" if breeding_path is None else "NONBREEDING"
                skips.append(SkipRow(taxa, taxon_id, None, "BREEDING+NONBREEDING", f"missing current AOH for {missing}"))
                continue
            assessment_id = IUCNFormatFilename.of_filename(nonbreeding_path).assessment_id
            worklist.append(WorkItem(
                taxa, taxon_id, assessment_id, "BREEDING+NONBREEDING",
                {"BREEDING": breeding_path, "NONBREEDING": nonbreeding_path},
            ))

        else:
            skips.append(SkipRow(taxa, taxon_id, None, "+".join(sorted(season_set)), f"unexpected season set {season_set}"))

    return worklist, skips


def sum_raster(path: Path) -> float:
    with RasterLayer.layer_from_file(path) as layer:
        return layer.sum()


def compute_resident(item: WorkItem, pnv_dir: Path, scenario_dir: Path) -> ResultRow | SkipRow:
    current_path = item.paths["RESIDENT"]
    historic_path = pnv_dir / current_path.name
    scenario_path = scenario_dir / current_path.name

    if not historic_path.exists():
        return SkipRow(item.taxa, item.taxon_id, item.assessment_id, item.season, "missing historic (pnv) AOH")

    current_aoh = sum_raster(current_path)
    historic_aoh = sum_raster(historic_path)
    if historic_aoh == 0.0:
        return SkipRow(item.taxa, item.taxon_id, item.assessment_id, item.season, "historic AOH is zero")

    if scenario_path.exists():
        scenario_aoh = sum_raster(scenario_path)
    else:
        scenario_aoh = 0.0

    old_persistence = calc_persistence_value(current_aoh, historic_aoh, exponent_func)
    new_persistence = calc_persistence_value(scenario_aoh, historic_aoh, exponent_func)

    return ResultRow(
        taxa=item.taxa, taxon_id=item.taxon_id, assessment_id=item.assessment_id, season=item.season,
        current_aoh=current_aoh, historic_aoh=historic_aoh, scenario_aoh=scenario_aoh,
        old_persistence=old_persistence, new_persistence=new_persistence,
        aggregate_delta_p=new_persistence - old_persistence,
    )


def compute_pair(item: WorkItem, pnv_dir: Path, scenario_dir: Path) -> ResultRow | SkipRow:
    current_breeding_path = item.paths["BREEDING"]
    current_nonbreeding_path = item.paths["NONBREEDING"]
    historic_breeding_path = pnv_dir / current_breeding_path.name
    historic_nonbreeding_path = pnv_dir / current_nonbreeding_path.name

    if not historic_breeding_path.exists() or not historic_nonbreeding_path.exists():
        missing = "BREEDING" if not historic_breeding_path.exists() else "NONBREEDING"
        return SkipRow(item.taxa, item.taxon_id, item.assessment_id, item.season, f"missing historic (pnv) AOH for {missing}")

    current_aoh_breeding = sum_raster(current_breeding_path)
    current_aoh_nonbreeding = sum_raster(current_nonbreeding_path)
    historic_aoh_breeding = sum_raster(historic_breeding_path)
    historic_aoh_nonbreeding = sum_raster(historic_nonbreeding_path)

    if historic_aoh_breeding == 0.0 or historic_aoh_nonbreeding == 0.0:
        return SkipRow(item.taxa, item.taxon_id, item.assessment_id, item.season, "historic AOH is zero")

    scenario_breeding_path = scenario_dir / current_breeding_path.name
    scenario_nonbreeding_path = scenario_dir / current_nonbreeding_path.name
    scenario_aoh_breeding = sum_raster(scenario_breeding_path) if scenario_breeding_path.exists() else 0.0
    scenario_aoh_nonbreeding = sum_raster(scenario_nonbreeding_path) if scenario_nonbreeding_path.exists() else 0.0

    old_persistence = (
        calc_persistence_value(current_aoh_breeding, historic_aoh_breeding, exponent_func) ** 0.5
        * calc_persistence_value(current_aoh_nonbreeding, historic_aoh_nonbreeding, exponent_func) ** 0.5
    )
    new_persistence = (
        calc_persistence_value(scenario_aoh_breeding, historic_aoh_breeding, exponent_func) ** 0.5
        * calc_persistence_value(scenario_aoh_nonbreeding, historic_aoh_nonbreeding, exponent_func) ** 0.5
    )

    if old_persistence < new_persistence and EXCL_NEGS:
        return SkipRow(item.taxa, item.taxon_id, item.assessment_id, item.season, "old persistence is greater than new persistence")

    
    return ResultRow(
        taxa=item.taxa, taxon_id=item.taxon_id, assessment_id=item.assessment_id, season=item.season,
        current_aoh_breeding=current_aoh_breeding, current_aoh_nonbreeding=current_aoh_nonbreeding,
        historic_aoh_breeding=historic_aoh_breeding, historic_aoh_nonbreeding=historic_aoh_nonbreeding,
        scenario_aoh_breeding=scenario_aoh_breeding, scenario_aoh_nonbreeding=scenario_aoh_nonbreeding,
        old_persistence=old_persistence, new_persistence=new_persistence,
        aggregate_delta_p=new_persistence - old_persistence,
    )


def compute_record(item: WorkItem, pnv_dir: Path, scenario_dir: Path) -> ResultRow | SkipRow:
    try:
        if item.season == "RESIDENT":
            return compute_resident(item, pnv_dir, scenario_dir)
        return compute_pair(item, pnv_dir, scenario_dir)
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Unexpected error processing %s taxon %s", item.taxa, item.taxon_id)
        return SkipRow(item.taxa, item.taxon_id, item.assessment_id, item.season, f"unexpected error: {exc}")


def process_taxa(
    taxa: str,
    current_dir: Path,
    species_info_dir: Path,
    pnv_dir: Path,
    scenario_dir: Path,
    max_workers: int,
) -> tuple[list[ResultRow], list[SkipRow]]:
    worklist, skips = build_worklist(taxa, current_dir, species_info_dir)

    results: list[ResultRow] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(compute_record, item, pnv_dir, scenario_dir): item for item in worklist}
        for future in as_completed(futures):
            record = future.result()
            if isinstance(record, SkipRow):
                skips.append(record)
            else:
                results.append(record)

    reason_counts: dict[str, int] = {}
    for skip in skips:
        reason_counts[skip.reason] = reason_counts.get(skip.reason, 0) + 1
    logger.info(
        "%s: %d candidates, %d processed, %d skipped (%s)",
        taxa, len(results) + len(skips), len(results), len(skips), reason_counts,
    )

    return results, skips


def pixel_total_for_taxa(year_dir: Path, taxa: str, scenario: str, curve: str) -> float:
    path = year_dir / "deltap_sum" / scenario / curve / f"{taxa}.tif"
    if not path.exists():
        logger.warning("Pixel-based deltap_sum raster not found at %s", path)
        return float("nan")
    return sum_raster(path)


def write_per_species_csv(rows: list[ResultRow], output_path: Path) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PER_SPECIES_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: getattr(row, col) for col in PER_SPECIES_COLUMNS})


def write_skipped_csv(rows: list[SkipRow], output_path: Path) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SKIPPED_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: getattr(row, col) for col in SKIPPED_COLUMNS})


def write_summary_csv(per_taxa_stats: list[dict], output_path: Path) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        for row in per_taxa_stats:
            writer.writerow(row)


def process_year(year: str) -> None:
    year_dir = Path(data_dirs_path) / year
    out_dir = year_dir / "deltap_aggregate" / SCENARIO / CURVE
    out_dir.mkdir(parents=True, exist_ok=True)

    max_workers = min(NUM_THREADS, os.cpu_count() or 1)

    all_results: list[ResultRow] = []
    all_skips: list[SkipRow] = []
    per_taxa_stats: list[dict] = []

    for taxa in TAXA:
        current_dir = year_dir / "aohs" / "current" / taxa
        info_dir = Path(species_info_path) / taxa / "current"
        pnv_dir = year_dir / "aohs" / "pnv" / taxa
        scenario_dir = year_dir / "aohs" / SCENARIO / taxa

        results, skips = process_taxa(taxa, current_dir, info_dir, pnv_dir, scenario_dir, max_workers)
        all_results.extend(results)
        all_skips.extend(skips)

        pixel_total = pixel_total_for_taxa(year_dir, taxa, SCENARIO, CURVE)
        aggregate_total = sum(r.aggregate_delta_p for r in results)
        per_taxa_stats.append({
            "taxa": taxa,
            "species_count": len(results),
            "skipped_count": len(skips),
            "aggregate_total": aggregate_total,
            "pixel_total": pixel_total,
            "difference": aggregate_total - pixel_total,
        })

    all_species_count = sum(s["species_count"] for s in per_taxa_stats)
    all_skipped_count = sum(s["skipped_count"] for s in per_taxa_stats)
    all_aggregate_total = sum(s["aggregate_total"] for s in per_taxa_stats)
    all_pixel_total = sum(s["pixel_total"] for s in per_taxa_stats)
    per_taxa_stats.append({
        "taxa": "all",
        "species_count": all_species_count,
        "skipped_count": all_skipped_count,
        "aggregate_total": all_aggregate_total,
        "pixel_total": all_pixel_total,
        "difference": all_aggregate_total - all_pixel_total,
    })

    write_per_species_csv(all_results, out_dir / "per_species.csv")
    write_skipped_csv(all_skips, out_dir / "skipped_species.csv")
    write_summary_csv(per_taxa_stats, out_dir / "summary.csv")

    logger.info("Year %s done. Summary written to %s", year, out_dir / "summary.csv")


def main() -> None:
    _, max_fd_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (max_fd_limit, max_fd_limit))

    for year in YEARS:
        process_year(year)


if __name__ == "__main__":
    main()
