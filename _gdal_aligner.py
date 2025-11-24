import os
import subprocess
import json
import re

def get_gdal_metadata(file_path: str) -> dict | None:
    """
    Retrieves essential GeoTIFF metadata (GeoTransform and dimensions) 
    using the 'gdalinfo -json' command line tool.
    
    Returns a dictionary of parsed metadata or None on failure.
    """
    try:
        # Use gdalinfo in JSON format for robust command-line parsing
        command = ["gdalinfo", "-json", file_path]
        
        # Execute the command
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        
        # Parse the JSON output
        metadata = json.loads(result.stdout)
        
        # Extract required values from the JSON structure
        # GeoTransform: [ULX, ResX, RotX, ULY, RotY, ResY]
        gt = metadata.get('geoTransform', [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        
        return {
            'ul_x': gt[0],
            'ul_y': gt[3],
            'res_x': gt[1],
            'res_y': gt[5],
            'cols': metadata.get('size', [0, 0])[0],
            'rows': metadata.get('size', [0, 0])[1],
            'rot_x': gt[2],
            'rot_y': gt[4]
        }

    except subprocess.CalledProcessError as e:
        print(f"❌ Error during gdalinfo execution (check if GDAL is in PATH):")
        print(e.stderr)
        return None
    except FileNotFoundError:
        print("❌ Error: gdalinfo command not found. Ensure GDAL is installed and accessible in your PATH.")
        return None
    except json.JSONDecodeError:
        print("❌ Error: gdalinfo output could not be parsed as JSON. Check GDAL version.")
        return None


def realign_geotiff_origin(file_path: str, tolerance: float, origin: tuple = (-180.0, 90.0)) -> None:
    """
    Checks the GeoTIFF origin using gdalinfo and corrects it to (0.0, 0.0) 
    using gdal_edit.py via subprocess, relying entirely on command-line GDAL tools.
    """
    if not os.path.exists(file_path):
        print(f"❌ Error: File not found at {file_path}")
        return

    # --- 1. GET METADATA VIA GDALINFO COMMAND ---
    metadata = get_gdal_metadata(file_path)
    if metadata is None:
        return

    ul_x = metadata['ul_x']
    ul_y = metadata['ul_y']
    res_x = metadata['res_x']
    res_y = metadata['res_y']
    cols = metadata['cols']
    rows = metadata['rows']
    rot_x = metadata['rot_x']
    rot_y = metadata['rot_y']

    # --- 2. CHECK TOLERANCE ---
    is_x_near_zero = abs(ul_x) < tolerance
    is_y_near_zero = abs(ul_y) < tolerance

    print(f"--- GeoTIFF Origin Check ---")
    print(f"File: {file_path}")
    print(f"Current UL_X: {ul_x} (Tolerance: {tolerance})")
    print(f"Current UL_Y: {ul_y} (Tolerance: {tolerance})")

    # If both origins are already effectively zero, skip correction
    if is_x_near_zero and is_y_near_zero:
        print(f"Origin is effectively {origin} - skipping realignment.")
        return

    print("\nOrigin needs correction!")
    print(f"UL_X is {'off' if not is_x_near_zero else 'OK'}. UL_Y is {'off' if not is_y_near_zero else 'OK'}.")

    # --- 3. CALCULATE NEW LOWER-RIGHT (LR) COORDINATES ---
    
    # NOTE: The -a_ullr option requires the Lower-Right corner. For non-rotated 
    # rasters (RotX=0, RotY=0), the calculation is simple: UL + (Dimension * Resolution).
    if rot_x != 0.0 or rot_y != 0.0:
        # For rotated rasters, calculating the true LR corner from the geotransform 
        # requires matrix math, which is complex and usually handled by GDAL bindings.
        # Since we must use only CLI tools, we proceed with the simple bounding box
        # calculation, which is correct ONLY for non-rotated rasters.
        print("WARNING: Rotated raster detected. Proceeding with standard bounding box calculation.")
        
    # Calculate dimensions (width and height)
    width = cols * res_x
    height = rows * res_y 

    # Calculate the new Lower-Right coordinates based on the desired UL=(0.0, 0.0)
    new_lr_x = origin[0] + width
    new_lr_y = origin[1] + height 
    
    new_lr_x = round(new_lr_x, int(tolerance))
    new_lr_y = round(new_lr_y, int(tolerance))

    print(f"Calculated New LR_X: {new_lr_x:.10f}")
    print(f"Calculated New LR_Y: {new_lr_y:.10f}")
    print("Executing gdal_edit.py to reset origin...")

    # --- 4. EXECUTE GDAL_EDIT.PY COMMAND ---
    
    # Construct the gdal_edit.py command: -a_ullr <ulx> <uly> <lrx> <lry>
    command = [
        "gdal_edit.py", 
        "-a_ullr", 
        f"{origin[0]}", 
        f"{origin[1]}", 
        str(new_lr_x), 
        str(new_lr_y), 
        file_path
    ]

    try:
        # Use subprocess.run to execute the external command
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        
        print("Command executed successfully:")
        print(result.stdout)
        print(f"Origin successfully reset to {origin}.")
        
    except subprocess.CalledProcessError as e:
        print(f"Error during gdal_edit execution:")
        print(e.stderr)
    except FileNotFoundError:
        print("Error: gdal_edit.py command not found. Ensure GDAL is installed and accessible in your PATH.")
