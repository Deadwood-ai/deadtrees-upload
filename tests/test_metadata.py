"""Tests for metadata parsing."""

import pytest
import pandas as pd
from pathlib import Path

from deadtrees_upload.metadata import (
	find_column_mapping,
	parse_metadata,
	REQUIRED_COLUMNS,
)
from deadtrees_upload.models import FileMetadata, LicenseEnum, PlatformEnum


def test_find_column_mapping_exact_match():
	"""Test column mapping with exact column names."""
	df = pd.DataFrame({
		"filename": ["test.tif"],
		"license": ["CC BY"],
		"platform": ["drone"],
		"authors": ["John Smith"],
	})
	
	mapping, missing = find_column_mapping(df)
	
	assert "filename" in mapping
	assert "license" in mapping
	assert "platform" in mapping
	assert "authors" in mapping
	assert len(missing) == 0


def test_find_column_mapping_aliases():
	"""Test column mapping with alias column names."""
	df = pd.DataFrame({
		"file_name": ["test.tif"],
		"licence": ["CC BY"],
		"sensor": ["drone"],
		"contributor": ["John Smith"],
	})
	
	mapping, missing = find_column_mapping(df)
	
	assert mapping.get("filename") == "file_name"
	assert mapping.get("license") == "licence"
	assert mapping.get("platform") == "sensor"
	assert mapping.get("authors") == "contributor"


def test_find_column_mapping_missing_required():
	"""Test column mapping with missing required columns."""
	df = pd.DataFrame({
		"filename": ["test.tif"],
		"license": ["CC BY"],
	})
	
	mapping, missing = find_column_mapping(df)
	
	assert "platform" in missing
	assert "authors" in missing


def test_parse_metadata_valid():
	"""Test parsing valid metadata."""
	df = pd.DataFrame({
		"filename": ["test.tif"],
		"license": ["CC BY"],
		"platform": ["drone"],
		"authors": ["John Smith; Jane Doe"],
	})
	
	mapping = {
		"filename": "filename",
		"license": "license",
		"platform": "platform",
		"authors": "authors",
	}
	
	metadata_list, errors = parse_metadata(df, mapping)
	
	assert len(metadata_list) == 1
	assert len(errors) == 0
	assert metadata_list[0].filename == "test.tif"
	assert metadata_list[0].license == LicenseEnum.cc_by
	assert metadata_list[0].platform == PlatformEnum.drone
	assert metadata_list[0].authors == ["John Smith", "Jane Doe"]


def test_parse_metadata_with_optional_fields():
	"""Test parsing metadata with optional fields."""
	df = pd.DataFrame({
		"filename": ["test.tif"],
		"license": ["CC BY-SA"],
		"platform": ["airborne"],
		"authors": ["Research Team"],
		"acquisition_year": ["2024"],
		"acquisition_month": ["6"],
		"additional_information": ["Test notes"],
	})
	
	mapping = {
		"filename": "filename",
		"license": "license",
		"platform": "platform",
		"authors": "authors",
		"acquisition_year": "acquisition_year",
		"acquisition_month": "acquisition_month",
		"additional_information": "additional_information",
	}
	
	metadata_list, errors = parse_metadata(df, mapping)
	
	assert len(metadata_list) == 1
	assert len(errors) == 0
	assert metadata_list[0].acquisition_year == 2024
	assert metadata_list[0].acquisition_month == 6
	assert metadata_list[0].additional_information == "Test notes"


def test_parse_metadata_invalid_license():
	"""Test parsing with invalid license value."""
	df = pd.DataFrame({
		"filename": ["test.tif"],
		"license": ["Invalid License"],
		"platform": ["drone"],
		"authors": ["John Smith"],
	})
	
	mapping = {
		"filename": "filename",
		"license": "license",
		"platform": "platform",
		"authors": "authors",
	}
	
	metadata_list, errors = parse_metadata(df, mapping)
	
	assert len(metadata_list) == 0
	assert len(errors) == 1


def test_parse_authors_from_string():
	"""Test parsing authors from semicolon-separated string."""
	metadata = FileMetadata(
		filename="test.tif",
		license=LicenseEnum.cc_by,
		platform=PlatformEnum.drone,
		authors="John Smith; Jane Doe; Bob Wilson",
	)
	
	assert metadata.authors == ["John Smith", "Jane Doe", "Bob Wilson"]


def test_license_normalization():
	"""Test license string normalization."""
	# Test various formats
	for license_str in ["CC BY", "cc by", "CC-BY", "CCBY"]:
		metadata = FileMetadata(
			filename="test.tif",
			license=license_str,
			platform=PlatformEnum.drone,
			authors=["Test"],
		)
		assert metadata.license == LicenseEnum.cc_by
