"""Tests for file validation."""

import pytest
from pathlib import Path
import tempfile
import zipfile

from deadtrees_upload.validation import (
	find_uploadable_files,
	detect_upload_type,
	validate_zip,
	match_files_to_metadata,
)
from deadtrees_upload.models import FileMetadata, UploadType, LicenseEnum, PlatformEnum


def test_find_uploadable_files_geotiff(tmp_path):
	"""Test finding GeoTIFF files."""
	# Create test files
	(tmp_path / "test1.tif").touch()
	(tmp_path / "test2.tiff").touch()
	(tmp_path / "readme.txt").touch()
	
	files, file_types = find_uploadable_files(tmp_path)
	
	assert len(files) == 2
	assert all(f.suffix.lower() in [".tif", ".tiff"] for f in files)
	assert file_types["test1.tif"] == "GeoTIFF"
	assert file_types["test2.tiff"] == "GeoTIFF"


def test_find_uploadable_files_zip(tmp_path):
	"""Test finding ZIP files."""
	(tmp_path / "images.zip").touch()
	(tmp_path / "data.zip").touch()
	
	files, file_types = find_uploadable_files(tmp_path)
	
	assert len(files) == 2
	assert file_types["images.zip"] == "ZIP"


def test_find_uploadable_files_mixed(tmp_path):
	"""Test finding mixed file types."""
	(tmp_path / "ortho.tif").touch()
	(tmp_path / "raw.zip").touch()
	(tmp_path / "notes.txt").touch()
	
	files, file_types = find_uploadable_files(tmp_path)
	
	assert len(files) == 2
	assert file_types["ortho.tif"] == "GeoTIFF"
	assert file_types["raw.zip"] == "ZIP"


def test_detect_upload_type():
	"""Test upload type detection."""
	assert detect_upload_type(Path("test.tif")) == UploadType.geotiff
	assert detect_upload_type(Path("test.tiff")) == UploadType.geotiff
	assert detect_upload_type(Path("test.zip")) == UploadType.raw_images_zip


def test_validate_zip_with_images(tmp_path):
	"""Test validating ZIP with images."""
	zip_path = tmp_path / "images.zip"
	
	with zipfile.ZipFile(zip_path, 'w') as zf:
		zf.writestr("image1.jpg", b"fake image data")
		zf.writestr("image2.jpg", b"fake image data")
		zf.writestr("image3.jpg", b"fake image data")
	
	result = validate_zip(zip_path)
	
	assert result.is_valid
	assert len(result.errors) == 0


def test_validate_zip_empty(tmp_path):
	"""Test validating empty ZIP."""
	zip_path = tmp_path / "empty.zip"
	
	with zipfile.ZipFile(zip_path, 'w') as zf:
		pass  # Empty ZIP
	
	result = validate_zip(zip_path)
	
	assert not result.is_valid
	assert "empty" in result.errors[0].lower()


def test_validate_zip_no_images(tmp_path):
	"""Test validating ZIP without images."""
	zip_path = tmp_path / "noimage.zip"
	
	with zipfile.ZipFile(zip_path, 'w') as zf:
		zf.writestr("readme.txt", b"text content")
		zf.writestr("data.csv", b"csv content")
	
	result = validate_zip(zip_path)
	
	assert not result.is_valid
	assert "no image" in result.errors[0].lower()


def test_match_files_to_metadata(tmp_path):
	"""Test matching files to metadata."""
	# Create test files
	file1 = tmp_path / "ortho_001.tif"
	file2 = tmp_path / "ortho_002.tif"
	file1.touch()
	file2.touch()
	
	# Create metadata
	metadata = [
		FileMetadata(
			filename="ortho_001.tif",
			license=LicenseEnum.cc_by,
			platform=PlatformEnum.drone,
			authors=["Test"],
		),
		FileMetadata(
			filename="ortho_002.tif",
			license=LicenseEnum.cc_by,
			platform=PlatformEnum.drone,
			authors=["Test"],
		),
	]
	
	matched, unmatched_files, unmatched_metadata = match_files_to_metadata(
		[file1, file2],
		metadata,
	)
	
	assert len(matched) == 2
	assert len(unmatched_files) == 0
	assert len(unmatched_metadata) == 0


def test_match_files_case_insensitive(tmp_path):
	"""Test case-insensitive file matching."""
	file1 = tmp_path / "ORTHO_001.TIF"
	file1.touch()
	
	metadata = [
		FileMetadata(
			filename="ortho_001.tif",
			license=LicenseEnum.cc_by,
			platform=PlatformEnum.drone,
			authors=["Test"],
		),
	]
	
	matched, unmatched_files, unmatched_metadata = match_files_to_metadata(
		[file1],
		metadata,
	)
	
	assert len(matched) == 1


def test_match_files_unmatched(tmp_path):
	"""Test unmatched files and metadata."""
	file1 = tmp_path / "ortho_001.tif"
	file2 = tmp_path / "ortho_003.tif"  # No metadata for this
	file1.touch()
	file2.touch()
	
	metadata = [
		FileMetadata(
			filename="ortho_001.tif",
			license=LicenseEnum.cc_by,
			platform=PlatformEnum.drone,
			authors=["Test"],
		),
		FileMetadata(
			filename="ortho_002.tif",  # No file for this
			license=LicenseEnum.cc_by,
			platform=PlatformEnum.drone,
			authors=["Test"],
		),
	]
	
	matched, unmatched_files, unmatched_metadata = match_files_to_metadata(
		[file1, file2],
		metadata,
	)
	
	assert len(matched) == 1
	assert "ortho_003.tif" in unmatched_files
	assert "ortho_002.tif" in unmatched_metadata
