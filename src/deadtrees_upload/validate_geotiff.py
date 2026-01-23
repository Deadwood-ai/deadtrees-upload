"""GeoTIFF file validation."""

from pathlib import Path
from typing import Tuple, Optional
from datetime import datetime

from .models import ValidationResult


def extract_date_from_geotiff(file_path: Path) -> Tuple[Optional[int], Optional[int], Optional[int]]:
	"""
	Try to extract acquisition date from GeoTIFF metadata.
	
	Checks for common date tags:
	- acquisitionStartDate / acquisitionEndDate (ODM processed)
	- TIFFTAG_DATETIME
	- DateTimeOriginal
	
	Args:
		file_path: Path to GeoTIFF file
	
	Returns:
		Tuple of (year, month, day) - any can be None if not found
	"""
	try:
		import rasterio
		
		with rasterio.open(file_path) as src:
			tags = src.tags()
			
			# Check for acquisition dates (ODM processed files)
			date_str = tags.get('acquisitionStartDate') or tags.get('acquisitionEndDate')
			
			# Check for TIFF DateTime
			if not date_str:
				date_str = tags.get('TIFFTAG_DATETIME') or tags.get('DateTime')
			
			if date_str:
				# Parse ISO format: 2019-09-29T01:48:04+00:00
				try:
					# Remove timezone suffix
					clean_str = date_str.split('+')[0].split('Z')[0]
					
					# Try ISO format
					if 'T' in clean_str:
						dt = datetime.strptime(clean_str, "%Y-%m-%dT%H:%M:%S")
					else:
						dt = datetime.strptime(clean_str, "%Y-%m-%d")
					
					return dt.year, dt.month, dt.day
				except ValueError:
					pass
			
			return None, None, None
	except Exception:
		return None, None, None


def validate_geotiff(file_path: Path) -> Tuple[ValidationResult, Tuple[Optional[int], Optional[int], Optional[int]]]:
	"""
	Validate a GeoTIFF file and extract date metadata if available.
	
	Checks:
	- File exists and is not empty
	- Valid CRS (required for processing)
	- At least 3 bands (RGB required)
	- Valid georeferencing (not a plain image)
	
	Args:
		file_path: Path to GeoTIFF
	
	Returns:
		Tuple of (ValidationResult, (year, month, day)) - date can be None
	"""
	warnings = []
	errors = []
	extracted_date = (None, None, None)
	
	if not file_path.exists():
		return ValidationResult(
			filename=file_path.name,
			is_valid=False,
			errors=["File does not exist"],
		), extracted_date
	
	# Check file size
	file_size = file_path.stat().st_size
	if file_size == 0:
		return ValidationResult(
			filename=file_path.name,
			is_valid=False,
			errors=["File is empty"],
		), extracted_date
	
	# Try to open with rasterio for more validation
	try:
		import rasterio
		
		with rasterio.open(file_path) as src:
			# Check for CRS - REQUIRED
			if src.crs is None:
				# Check if it has transform (coordinates but no CRS)
				has_transform = src.transform and src.transform != rasterio.transform.Affine.identity()
				origin = [src.transform.c, src.transform.f] if src.transform else [0, 0]
				
				if has_transform and (origin[0] != 0 or origin[1] != 0):
					errors.append(
						f"File has coordinates (origin: {origin[0]:.1f}, {origin[1]:.1f}) but no CRS definition. "
						"Please re-export with embedded CRS or include a .prj file."
					)
				else:
					errors.append(
						"File has no coordinate reference system (CRS) or georeferencing. "
						"This appears to be a plain image, not a georeferenced orthomosaic. "
						"Please upload a GeoTIFF with embedded CRS."
					)
			else:
				# Check for invalid CRS types
				crs_str = str(src.crs)
				if "LOCAL_CS" in crs_str or "EngineeringCRS" in crs_str:
					errors.append(
						f"Invalid CRS type: {crs_str[:50]}... "
						"Local/Engineering CRS cannot be processed. "
						"Please re-export with a standard geographic or projected CRS (e.g., EPSG:4326, UTM)."
					)
			
			# Check band count - MINIMUM 3 for RGB
			if src.count == 0:
				errors.append("No bands in raster")
			elif src.count < 3:
				errors.append(
					f"File has only {src.count} band(s). RGB orthomosaics require at least 3 bands. "
					"Single-band rasters (grayscale, elevation, indices) are not supported."
				)
			elif src.count > 4:
				warnings.append(
					f"File has {src.count} bands. Only first 3 (RGB) will be used for processing."
				)
			
			# Check for valid bounds
			bounds = src.bounds
			if bounds.left == bounds.right or bounds.top == bounds.bottom:
				errors.append("Invalid bounds - file appears to be corrupted or has zero extent")
			
			# Check data type
			dtype = src.dtypes[0] if src.dtypes else None
			if dtype and "complex" in str(dtype):
				warnings.append(f"Complex data type ({dtype}) may not be supported")
		
		# Extract date from metadata
		extracted_date = extract_date_from_geotiff(file_path)
		if extracted_date[0]:
			warnings.append(f"Extracted date from file: {extracted_date[0]}-{extracted_date[1] or '??'}-{extracted_date[2] or '??'}")
	
	except ImportError:
		warnings.append("rasterio not available - skipping detailed validation")
	except Exception as e:
		if "rasterio" in str(type(e).__module__):
			errors.append(f"Cannot read GeoTIFF: {str(e)}")
		else:
			warnings.append(f"Validation warning: {str(e)}")
	
	return ValidationResult(
		filename=file_path.name,
		is_valid=len(errors) == 0,
		warnings=warnings,
		errors=errors,
	), extracted_date
