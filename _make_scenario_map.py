import argparse
from pathlib import Path
from typing import Optional

import yirgacheffe.operators as yo
from alive_progress import alive_bar
from yirgacheffe.layers import RasterLayer

from osgeo import gdal
gdal.SetCacheMax(1 * 1024 * 1024 * 1024)

SCENARIO_CODE = 1403
CODES_TO_REPLACE = [
                    200, # Urban and built-up land     
                    ]

def make_scenario_map(
    current_path: Path,
    output_path: Path,
    concurrency: Optional[int],
    show_progress: bool,
    scenario_codes_to_replace: list = CODES_TO_REPLACE,
    scenario_code_to_become: int = SCENARIO_CODE,
) -> None:
    
    with RasterLayer.layer_from_file(current_path) as current:

        condition = current.isin(scenario_codes_to_replace)
        scenario_map = yo.where(condition, current, scenario_code_to_become)

        with RasterLayer.empty_raster_layer_like(
            scenario_map,
            filename=output_path,
            threads=16
        ) as result:
            if show_progress:
                with alive_bar(manual=True) as bar:
                    scenario_map.parallel_save(result, callback=bar, parallelism=concurrency)
            else:
                scenario_map.parallel_save(result, parallelism=concurrency)

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the scenario map.")
    parser.add_argument(
        '--current',
        type=Path,
        help='Path of current map',
        required=True,
        dest='current_path',
    )
    parser.add_argument(
        '--output',
        type=Path,
        help='Path where final map should be stored',
        required=True,
        dest='results_path',
    )
    parser.add_argument(
        '-j',
        type=int,
        help='Number of concurrent threads to use for calculation.',
        required=False,
        default=None,
        dest='concurrency',
    )
    parser.add_argument(
        '-p',
        help="Show progress indicator",
        default=False,
        required=False,
        action='store_true',
        dest='show_progress',
    )
    args = parser.parse_args()

    make_scenario_map(
        args.current_path,
        args.results_path,
        args.concurrency,
        args.show_progress,
    )

if __name__ == "__main__":
    main()
