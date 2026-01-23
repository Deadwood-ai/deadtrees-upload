"""Metadata file parsing and column mapping."""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import pandas as pd
from pydantic import ValidationError

from .models import FileMetadata, LicenseEnum, PlatformEnum, DataAccessEnum


def parse_date_string(date_str: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
	"""
	Parse a date string into (year, month, day).
	
	Supports formats:
	- YYYY-MM-DD, YYYY/MM/DD
	- DD-MM-YYYY, DD/MM/YYYY
	- MM-DD-YYYY, MM/DD/YYYY
	- YYYY-MM, YYYY/MM
	- YYYY
	- ISO format with time
	
	Returns:
		Tuple of (year, month, day) - any can be None if not parsed
	"""
	if not date_str or not isinstance(date_str, str):
		return None, None, None
	
	date_str = date_str.strip()
	
	# Try various formats
	formats = [
		("%Y-%m-%d", True),           # 2024-06-15
		("%Y/%m/%d", True),           # 2024/06/15
		("%d-%m-%Y", False),          # 15-06-2024
		("%d/%m/%Y", False),          # 15/06/2024
		("%Y-%m-%dT%H:%M:%S", True),  # ISO with time
		("%Y-%m-%dT%H:%M:%S%z", True),  # ISO with timezone
		("%Y-%m", True),              # 2024-06
		("%Y/%m", True),              # 2024/06
		("%m-%Y", False),             # 06-2024
		("%m/%Y", False),             # 06/2024
	]
	
	for fmt, _ in formats:
		try:
			# Handle timezone suffix like +00:00
			clean_str = date_str.split('+')[0].split('Z')[0]
			dt = datetime.strptime(clean_str, fmt.replace('%z', ''))
			
			# For formats without day, return None for day
			if '%d' not in fmt:
				return dt.year, dt.month, None
			return dt.year, dt.month, dt.day
		except ValueError:
			continue
	
	# Try just year
	try:
		year = int(date_str)
		if 1980 <= year <= 2099:
			return year, None, None
	except ValueError:
		pass
	
	return None, None, None


class MetadataError(Exception):
	"""Error parsing or validating metadata."""
	pass


# Standard column names and their aliases
COLUMN_ALIASES: Dict[str, List[str]] = {
	"filename": ["filename", "file_name", "file", "name", "ortho", "image"],
	"license": ["license", "licence", "lic"],
	"platform": ["platform", "plat", "sensor", "type"],
	"authors": ["authors", "author", "contributor", "contributors", "creator", "creators"],
	"acquisition_year": ["acquisition_year", "year", "acq_year", "aquisition_year", "date_year"],
	"acquisition_month": ["acquisition_month", "month", "acq_month", "aquisition_month", "date_month"],
	"acquisition_day": ["acquisition_day", "day", "acq_day", "aquisition_day", "date_day"],
	"acquisition_date": ["acquisition_date", "date", "acq_date", "aquisition_date", "capture_date", "flight_date"],
	"data_access": ["data_access", "access", "visibility", "public"],
	"additional_information": ["additional_information", "additional_info", "info", "notes", "description", "comment", "comments"],
	"citation_doi": ["citation_doi", "doi", "citation"],
}

REQUIRED_COLUMNS = ["filename", "license", "platform", "authors"]


def read_metadata_file(file_path: Path) -> pd.DataFrame:
	"""
	Read metadata from CSV or Excel file.
	
	Args:
		file_path: Path to metadata file
	
	Returns:
		DataFrame with metadata
	
	Raises:
		MetadataError: If file cannot be read
	"""
	suffix = file_path.suffix.lower()
	
	try:
		if suffix == ".csv":
			df = pd.read_csv(file_path, dtype=str)
		elif suffix in [".xlsx", ".xls"]:
			df = pd.read_excel(file_path, dtype=str)
		else:
			raise MetadataError(f"Unsupported file format: {suffix}. Use .csv or .xlsx")
		
		# Clean column names
		df.columns = [str(col).strip().lower() for col in df.columns]
		
		# Replace NaN with None
		df = df.where(pd.notna(df), None)
		
		return df
		
	except pd.errors.EmptyDataError:
		raise MetadataError("Metadata file is empty")
	except Exception as e:
		raise MetadataError(f"Error reading metadata file: {str(e)}")


def find_column_mapping(df: pd.DataFrame) -> Tuple[Dict[str, str], List[str]]:
	"""
	Find mapping between standard column names and actual column names.
	
	Args:
		df: DataFrame with metadata
	
	Returns:
		Tuple of (mapping dict, list of missing required columns)
	"""
	mapping = {}
	actual_columns = list(df.columns)
	
	for standard_name, aliases in COLUMN_ALIASES.items():
		for alias in aliases:
			alias_lower = alias.lower()
			for actual_col in actual_columns:
				if actual_col == alias_lower:
					mapping[standard_name] = actual_col
					break
			if standard_name in mapping:
				break
	
	# Check for missing required columns
	missing = [col for col in REQUIRED_COLUMNS if col not in mapping]
	
	return mapping, missing


def suggest_column_matches(df: pd.DataFrame, target_column: str) -> List[str]:
	"""
	Suggest possible column matches for a missing required column.
	
	Args:
		df: DataFrame with metadata
		target_column: The standard column name we're looking for
	
	Returns:
		List of candidate column names from the DataFrame
	"""
	# Get columns not yet mapped
	candidates = list(df.columns)
	
	# Simple fuzzy matching based on substring
	target_lower = target_column.lower()
	scored = []
	
	for col in candidates:
		col_lower = col.lower()
		# Exact match
		if col_lower == target_lower:
			scored.append((col, 100))
		# Contains target
		elif target_lower in col_lower or col_lower in target_lower:
			scored.append((col, 50))
		# First letter match
		elif col_lower[0] == target_lower[0]:
			scored.append((col, 10))
		else:
			scored.append((col, 0))
	
	# Sort by score, then alphabetically
	scored.sort(key=lambda x: (-x[1], x[0]))
	
	return [col for col, _ in scored[:5]]


def parse_metadata(
	df: pd.DataFrame,
	column_mapping: Dict[str, str],
) -> Tuple[List[FileMetadata], List[Tuple[int, str]]]:
	"""
	Parse DataFrame rows into FileMetadata objects.
	
	Args:
		df: DataFrame with metadata
		column_mapping: Mapping from standard names to actual column names
	
	Returns:
		Tuple of (list of valid FileMetadata, list of (row_index, error_message))
	"""
	metadata_list = []
	errors = []
	
	for idx, row in df.iterrows():
		row_num = idx + 2  # +2 for 1-based indexing and header row
		
		try:
			# Build data dict from mapping
			data = {}
			for standard_name, actual_col in column_mapping.items():
				value = row.get(actual_col)
				if value is not None and str(value).strip():
					data[standard_name] = value
			
			# Handle date column - parse into year/month/day if present
			if "acquisition_date" in data and data["acquisition_date"]:
				year, month, day = parse_date_string(str(data["acquisition_date"]))
				if year and "acquisition_year" not in data:
					data["acquisition_year"] = year
				if month and "acquisition_month" not in data:
					data["acquisition_month"] = month
				if day and "acquisition_day" not in data:
					data["acquisition_day"] = day
				# Remove the date field as it's not in the model
				del data["acquisition_date"]
			
			# Validate required fields are present
			for required in REQUIRED_COLUMNS:
				if required not in data or not data[required]:
					raise ValueError(f"Missing required field: {required}")
			
			# Parse and validate
			metadata = FileMetadata(**data)
			metadata_list.append(metadata)
			
		except ValidationError as e:
			error_msgs = "; ".join([f"{err['loc'][0]}: {err['msg']}" for err in e.errors()])
			errors.append((row_num, error_msgs))
		except ValueError as e:
			errors.append((row_num, str(e)))
		except Exception as e:
			errors.append((row_num, f"Unexpected error: {str(e)}"))
	
	return metadata_list, errors


def get_valid_values_help() -> Dict[str, List[str]]:
	"""Get valid values for enum fields."""
	return {
		"license": [e.value for e in LicenseEnum],
		"platform": [e.value for e in PlatformEnum],
		"data_access": [e.value for e in DataAccessEnum],
	}
