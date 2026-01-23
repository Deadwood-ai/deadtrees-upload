"""File and metadata validation."""

from pathlib import Path
from typing import List, Dict, Tuple, Optional

from .models import FileMetadata, ValidationResult, UploadType
from .validate_geotiff import validate_geotiff
from .validate_zip import validate_zip


class ValidationError(Exception):
	"""Validation error."""
	pass


# Supported file extensions
GEOTIFF_EXTENSIONS = {".tif", ".tiff", ".geotiff"}
ZIP_EXTENSIONS = {".zip"}


def find_uploadable_files(directory: Path) -> Tuple[List[Path], Dict[str, str]]:
	"""
	Find all uploadable files in a directory.
	
	Args:
		directory: Path to search
	
	Returns:
		Tuple of (list of file paths, dict of filename -> file type)
	"""
	files = []
	file_types = {}
	
	if not directory.exists():
		raise ValidationError(f"Directory does not exist: {directory}")
	
	if not directory.is_dir():
		raise ValidationError(f"Path is not a directory: {directory}")
	
	for file_path in directory.iterdir():
		if not file_path.is_file():
			continue
		
		suffix = file_path.suffix.lower()
		
		if suffix in GEOTIFF_EXTENSIONS:
			files.append(file_path)
			file_types[file_path.name] = "GeoTIFF"
		elif suffix in ZIP_EXTENSIONS:
			files.append(file_path)
			file_types[file_path.name] = "ZIP"
	
	return files, file_types


def detect_upload_type(file_path: Path) -> UploadType:
	"""
	Detect the upload type based on file extension.
	
	Args:
		file_path: Path to file
	
	Returns:
		UploadType enum value
	"""
	suffix = file_path.suffix.lower()
	
	if suffix in GEOTIFF_EXTENSIONS:
		return UploadType.geotiff
	elif suffix in ZIP_EXTENSIONS:
		return UploadType.raw_images_zip
	else:
		raise ValidationError(f"Unsupported file type: {suffix}")


def validate_file(file_path: Path) -> Tuple[ValidationResult, Tuple[Optional[int], Optional[int], Optional[int]]]:
	"""
	Validate a file based on its type.
	
	Args:
		file_path: Path to file
	
	Returns:
		Tuple of (ValidationResult, extracted_date)
	"""
	suffix = file_path.suffix.lower()
	
	if suffix in GEOTIFF_EXTENSIONS:
		return validate_geotiff(file_path)
	elif suffix in ZIP_EXTENSIONS:
		return validate_zip(file_path), (None, None, None)
	else:
		return ValidationResult(
			filename=file_path.name,
			is_valid=False,
			errors=[f"Unsupported file type: {suffix}"],
		), (None, None, None)


def match_files_to_metadata(
	files: List[Path],
	metadata_list: List[FileMetadata],
) -> Tuple[List[FileMetadata], List[str], List[str]]:
	"""
	Match files to metadata entries by filename.
	
	Args:
		files: List of file paths
		metadata_list: List of metadata entries
	
	Returns:
		Tuple of (matched metadata with file_path set, unmatched files, unmatched metadata)
	"""
	# Create lookup by filename
	file_lookup: Dict[str, Path] = {f.name.lower(): f for f in files}
	metadata_lookup: Dict[str, FileMetadata] = {m.filename.lower(): m for m in metadata_list}
	
	matched = []
	unmatched_files = []
	unmatched_metadata = []
	
	# Match metadata to files
	for filename_lower, metadata in metadata_lookup.items():
		if filename_lower in file_lookup:
			metadata.file_path = file_lookup[filename_lower]
			metadata.upload_type = detect_upload_type(metadata.file_path)
			matched.append(metadata)
		else:
			unmatched_metadata.append(metadata.filename)
	
	# Find files without metadata
	matched_filenames = {m.filename.lower() for m in matched}
	for file_path in files:
		if file_path.name.lower() not in matched_filenames:
			unmatched_files.append(file_path.name)
	
	return matched, unmatched_files, unmatched_metadata


def validate_all(
	matched_metadata: List[FileMetadata],
) -> List[ValidationResult]:
	"""
	Validate all matched files and apply extracted dates to metadata.
	
	Args:
		matched_metadata: List of metadata entries with file_path set
	
	Returns:
		List of ValidationResult
	"""
	results = []
	
	for metadata in matched_metadata:
		if metadata.file_path is None:
			results.append(ValidationResult(
				filename=metadata.filename,
				is_valid=False,
				errors=["No file path set"],
			))
			continue
		
		result, extracted_date = validate_file(metadata.file_path)
		
		# Apply extracted date to metadata if not already set
		year, month, day = extracted_date
		if year and metadata.acquisition_year is None:
			metadata.acquisition_year = year
		if month and metadata.acquisition_month is None:
			metadata.acquisition_month = month
		if day and metadata.acquisition_day is None:
			metadata.acquisition_day = day
		
		result.metadata = metadata
		results.append(result)
	
	return results
