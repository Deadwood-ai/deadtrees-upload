"""Comprehensive tests for all deadtrees-upload features.

This is the main consolidated test file. All tests are organized by module.
"""

import pytest
from pathlib import Path
import tempfile
import json
import time
import zipfile
import pandas as pd

# Get fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures"


# =============================================================================
# FIXTURES
# =============================================================================

class TestFixtures:
	"""Verify test fixtures are in place."""
	
	def test_geotiff_fixtures_exist(self):
		assert (FIXTURES_DIR / "test_with_date.tif").exists()
		assert (FIXTURES_DIR / "test_no_date.tif").exists()
		assert (FIXTURES_DIR / "test_partial_date.tif").exists()
	
	def test_zip_fixtures_exist(self):
		assert (FIXTURES_DIR / "test_images_with_exif.zip").exists()
		assert (FIXTURES_DIR / "test_images_no_exif.zip").exists()


# =============================================================================
# MODELS (models.py)
# =============================================================================

class TestModels:
	"""Tests for Pydantic models."""
	
	def test_license_enum_values(self):
		from deadtrees_upload.models import LicenseEnum
		assert LicenseEnum.cc_by.value == "CC BY"
		assert LicenseEnum.cc_by_sa.value == "CC BY-SA"
		assert LicenseEnum.cc_by_nc_sa.value == "CC BY-NC-SA"
	
	def test_platform_enum_only_drone_and_airborne(self):
		from deadtrees_upload.models import PlatformEnum
		assert PlatformEnum.drone.value == "drone"
		assert PlatformEnum.airborne.value == "airborne"
		assert not hasattr(PlatformEnum, "satellite")
	
	def test_file_metadata_required_fields(self):
		from deadtrees_upload.models import FileMetadata, LicenseEnum, PlatformEnum
		
		metadata = FileMetadata(
			filename="test.tif",
			license=LicenseEnum.cc_by,
			platform=PlatformEnum.drone,
			authors=["Test"],
			acquisition_year=2024,
		)
		assert metadata.filename == "test.tif"
		assert metadata.acquisition_year == 2024
	
	def test_file_metadata_missing_year_raises(self):
		from deadtrees_upload.models import FileMetadata, LicenseEnum, PlatformEnum
		from pydantic import ValidationError
		
		with pytest.raises(ValidationError) as exc_info:
			FileMetadata(
				filename="test.tif",
				license=LicenseEnum.cc_by,
				platform=PlatformEnum.drone,
				authors=["Test"],
			)
		assert "acquisition_year" in str(exc_info.value)
	
	def test_file_metadata_optional_fields_default_none(self):
		from deadtrees_upload.models import FileMetadata, LicenseEnum, PlatformEnum
		
		metadata = FileMetadata(
			filename="test.tif",
			license=LicenseEnum.cc_by,
			platform=PlatformEnum.drone,
			authors=["Test"],
			acquisition_year=2024,
		)
		assert metadata.acquisition_month is None
		assert metadata.acquisition_day is None
		assert metadata.citation_doi is None
		assert metadata.additional_information is None
	
	def test_file_metadata_authors_from_string(self):
		from deadtrees_upload.models import FileMetadata, LicenseEnum, PlatformEnum
		
		metadata = FileMetadata(
			filename="test.tif",
			license=LicenseEnum.cc_by,
			platform=PlatformEnum.drone,
			authors="John; Jane; Bob",
			acquisition_year=2024,
		)
		assert metadata.authors == ["John", "Jane", "Bob"]
	
	def test_license_normalization(self):
		from deadtrees_upload.models import FileMetadata, LicenseEnum, PlatformEnum
		
		for license_str in ["CC BY", "cc by", "CC-BY", "CCBY"]:
			metadata = FileMetadata(
				filename="test.tif",
				license=license_str,
				platform=PlatformEnum.drone,
				authors=["Test"],
				acquisition_year=2024,
			)
			assert metadata.license == LicenseEnum.cc_by
	
	def test_license_normalization_aliases(self):
		from deadtrees_upload.models import FileMetadata, LicenseEnum, PlatformEnum
		
		cases = {
			"CC BY 4.0": LicenseEnum.cc_by,
			"cc-by-4.0": LicenseEnum.cc_by,
			"CC BY-SA 4.0": LicenseEnum.cc_by_sa,
			"cc-by-nc-sa-4.0": LicenseEnum.cc_by_nc_sa,
			"cc-by-nc-4.0": LicenseEnum.cc_by_nc,
			"MIT License": LicenseEnum.mit,
		}
		
		for license_str, expected in cases.items():
			metadata = FileMetadata(
				filename="test.tif",
				license=license_str,
				platform=PlatformEnum.drone,
				authors=["Test"],
				acquisition_year=2024,
			)
			assert metadata.license == expected
	
	def test_platform_normalization_aliases(self):
		from deadtrees_upload.models import FileMetadata, PlatformEnum, LicenseEnum
		
		cases = {
			"UAV": PlatformEnum.drone,
			"uavs": PlatformEnum.drone,
			"aircraft": PlatformEnum.airborne,
			"airbone": PlatformEnum.airborne,
			"Airplane": PlatformEnum.airborne,
		}
		
		for platform_str, expected in cases.items():
			metadata = FileMetadata(
				filename="test.tif",
				license=LicenseEnum.cc_by,
				platform=platform_str,
				authors=["Test"],
				acquisition_year=2024,
			)
			assert metadata.platform == expected
	
	def test_validation_result(self):
		from deadtrees_upload.models import ValidationResult
		
		result = ValidationResult(
			filename="test.tif",
			is_valid=True,
			warnings=["Warning 1"],
			errors=[],
		)
		assert result.is_valid
		assert len(result.warnings) == 1
	
	def test_upload_result(self):
		from deadtrees_upload.models import UploadResult
		
		result = UploadResult(filename="test.tif", success=True, dataset_id=123)
		assert result.success
		assert result.dataset_id == 123


# =============================================================================
# METADATA PARSING (metadata.py)
# =============================================================================

class TestMetadata:
	"""Tests for metadata file parsing."""
	
	def test_find_column_mapping_exact_match(self):
		from deadtrees_upload.metadata import find_column_mapping
		
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
	
	def test_find_column_mapping_aliases(self):
		from deadtrees_upload.metadata import find_column_mapping
		
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
	
	def test_find_column_mapping_missing_required(self):
		from deadtrees_upload.metadata import find_column_mapping
		
		df = pd.DataFrame({
			"filename": ["test.tif"],
			"license": ["CC BY"],
		})
		
		mapping, missing = find_column_mapping(df)
		
		assert "platform" in missing
		assert "authors" in missing
	
	def test_parse_metadata_valid(self):
		from deadtrees_upload.metadata import parse_metadata
		from deadtrees_upload.models import LicenseEnum, PlatformEnum
		
		df = pd.DataFrame({
			"filename": ["test.tif"],
			"license": ["CC BY"],
			"platform": ["drone"],
			"authors": ["John Smith; Jane Doe"],
			"acquisition_year": [2024],
		})
		
		mapping = {col: col for col in df.columns}
		metadata_list, errors = parse_metadata(df, mapping)
		
		assert len(metadata_list) == 1
		assert len(errors) == 0
		assert metadata_list[0].filename == "test.tif"
		assert metadata_list[0].license == LicenseEnum.cc_by
		assert metadata_list[0].platform == PlatformEnum.drone
		assert metadata_list[0].authors == ["John Smith", "Jane Doe"]
		assert metadata_list[0].acquisition_year == 2024
	
	def test_parse_metadata_with_acquisition_date(self):
		from deadtrees_upload.metadata import parse_metadata
		
		df = pd.DataFrame({
			"filename": ["test.tif"],
			"license": ["CC BY"],
			"platform": ["drone"],
			"authors": ["Author"],
			"acquisition_date": ["2024-06-15"],
		})
		
		mapping = {col: col for col in df.columns}
		metadata_list, errors = parse_metadata(df, mapping)
		
		assert len(metadata_list) == 1
		assert len(errors) == 0
		assert metadata_list[0].acquisition_year == 2024
		assert metadata_list[0].acquisition_month == 6
		assert metadata_list[0].acquisition_day == 15
	
	def test_parse_metadata_with_optional_fields(self):
		from deadtrees_upload.metadata import parse_metadata
		
		df = pd.DataFrame({
			"filename": ["test.tif"],
			"license": ["CC BY-SA"],
			"platform": ["airborne"],
			"authors": ["Research Team"],
			"acquisition_year": ["2024"],
			"acquisition_month": ["6"],
			"additional_information": ["Test notes"],
		})
		
		mapping = {col: col for col in df.columns}
		metadata_list, errors = parse_metadata(df, mapping)
		
		assert len(metadata_list) == 1
		assert len(errors) == 0
		assert metadata_list[0].acquisition_year == 2024
		assert metadata_list[0].acquisition_month == 6
		assert metadata_list[0].additional_information == "Test notes"
	
	def test_parse_metadata_invalid_license(self):
		from deadtrees_upload.metadata import parse_metadata
		
		df = pd.DataFrame({
			"filename": ["test.tif"],
			"license": ["Invalid License"],
			"platform": ["drone"],
			"authors": ["John Smith"],
		})
		
		mapping = {col: col for col in df.columns}
		metadata_list, errors = parse_metadata(df, mapping)
		
		assert len(metadata_list) == 0
		assert len(errors) >= 1
	
	def test_parse_metadata_missing_required(self):
		from deadtrees_upload.metadata import parse_metadata
		
		df = pd.DataFrame({
			"filename": ["test.tif"],
			"license": ["CC BY"],
		})
		
		mapping = {col: col for col in df.columns}
		metadata_list, errors = parse_metadata(df, mapping)
		
		assert len(metadata_list) == 0
		assert len(errors) > 0


# =============================================================================
# DEDUP & SESSION (dedup.py)
# =============================================================================

class TestDedup:
	"""Tests for duplicate detection and session management."""
	
	def test_get_file_identifier(self):
		from deadtrees_upload.dedup import get_file_identifier
		
		tif_path = FIXTURES_DIR / "test_with_date.tif"
		hash1 = get_file_identifier(tif_path)
		hash2 = get_file_identifier(tif_path)
		assert hash1 == hash2
		assert len(hash1) == 64  # SHA256 hex
	
	def test_different_files_different_hashes(self):
		from deadtrees_upload.dedup import get_file_identifier
		
		hash1 = get_file_identifier(FIXTURES_DIR / "test_with_date.tif")
		hash2 = get_file_identifier(FIXTURES_DIR / "test_no_date.tif")
		assert hash1 != hash2
	
	def test_session_state_create(self):
		from deadtrees_upload.dedup import UploadSessionState
		
		session = UploadSessionState.create(
			data_directory="/path/to/data",
			metadata_file="/path/to/metadata.csv",
			api_url="http://api.example.com",
		)
		
		assert session.session_id is not None
		assert len(session.session_id) == 8
		assert session.data_directory == "/path/to/data"
		assert session.files_total == 0
	
	def test_session_state_mark_completed(self):
		from deadtrees_upload.dedup import UploadSessionState
		
		session = UploadSessionState.create("/data", "/meta.csv", "http://api")
		session.files_total = 3
		
		session.mark_completed("file1.tif", dataset_id=100)
		
		assert "file1.tif" in session.files_completed
		assert session.dataset_ids["file1.tif"] == 100
		assert session.files_pending == 2
	
	def test_session_state_mark_failed(self):
		from deadtrees_upload.dedup import UploadSessionState
		
		session = UploadSessionState.create("/data", "/meta.csv", "http://api")
		session.files_total = 2
		
		session.mark_failed("file2.tif", "Connection error")
		
		assert "file2.tif" in session.files_failed
		assert session.files_failed["file2.tif"] == "Connection error"
	
	def test_session_state_should_process(self):
		from deadtrees_upload.dedup import UploadSessionState
		
		session = UploadSessionState.create("/data", "/meta.csv", "http://api")
		session.files_total = 3
		session.mark_completed("file1.tif", 100)
		session.mark_skipped("file2.tif", "duplicate")
		
		assert not session.should_process("file1.tif")
		assert not session.should_process("file2.tif")
		assert session.should_process("file3.tif")
	
	def test_session_state_is_complete(self):
		from deadtrees_upload.dedup import UploadSessionState
		
		session = UploadSessionState.create("/data", "/meta.csv", "http://api")
		session.files_total = 2
		
		assert not session.is_complete
		
		session.mark_completed("file1.tif", 100)
		session.mark_completed("file2.tif", 101)
		
		assert session.is_complete
	
	def test_session_state_save_and_load(self):
		from deadtrees_upload.dedup import UploadSessionState
		
		with tempfile.TemporaryDirectory() as tmpdir:
			session_path = Path(tmpdir) / "session.json"
			
			session1 = UploadSessionState.create("/data", "/meta.csv", "http://api")
			session1.files_total = 5
			session1.mark_completed("file1.tif", 100)
			session1.save(session_path)
			
			session2 = UploadSessionState.load(session_path)
			assert session2.session_id == session1.session_id
			assert session2.files_total == 5
			assert "file1.tif" in session2.files_completed
	
	def test_find_duplicates_by_hash(self):
		from deadtrees_upload.dedup import find_duplicates_by_hash
		
		file_hashes = {
			"file1.tif": "hash_a",
			"file2.tif": "hash_b",
			"file3.tif": "hash_c",
		}
		known_hashes = {"hash_a", "hash_c"}
		
		duplicates = find_duplicates_by_hash(file_hashes, known_hashes)
		
		assert "file1.tif" in duplicates
		assert "file2.tif" not in duplicates
		assert "file3.tif" in duplicates
	
	def test_get_session_file_path(self):
		from deadtrees_upload.dedup import get_session_file_path
		
		path = get_session_file_path(Path("/data/uploads"))
		assert path == Path("/data/uploads/.deadtrees-upload-session.json")


# =============================================================================
# AUTH (auth.py)
# =============================================================================

class TestAuth:
	"""Tests for authentication module (unit tests without API)."""
	
	def test_auth_session_is_expired(self):
		from deadtrees_upload.auth import AuthSession
		
		expired_session = AuthSession(
			access_token="token",
			refresh_token="refresh",
			user_id="user123",
			expires_at=time.time() - 100,
			supabase_url="http://supabase",
			supabase_key="key",
		)
		assert expired_session.is_expired()
		
		valid_session = AuthSession(
			access_token="token",
			refresh_token="refresh",
			user_id="user123",
			expires_at=time.time() + 3600,
			supabase_url="http://supabase",
			supabase_key="key",
		)
		assert not valid_session.is_expired()
	
	def test_auth_session_is_expired_with_buffer(self):
		from deadtrees_upload.auth import AuthSession
		
		session = AuthSession(
			access_token="token",
			refresh_token="refresh",
			user_id="user123",
			expires_at=time.time() + 200,
			supabase_url="http://supabase",
			supabase_key="key",
		)
		assert session.is_expired(buffer_seconds=300)
		assert not session.is_expired(buffer_seconds=100)
	
	def test_auth_error(self):
		from deadtrees_upload.auth import AuthError
		
		error = AuthError("Test error")
		assert str(error) == "Test error"
	
	def test_save_and_load_auth_session(self, tmp_path, monkeypatch):
		from deadtrees_upload.auth import AuthSession, save_auth_session, load_auth_session, get_auth_session_path
		
		monkeypatch.setenv("DEADTREES_UPLOAD_CACHE_DIR", str(tmp_path))
		api_url = "http://api.example.com"
		
		session = AuthSession(
			access_token="token",
			refresh_token="refresh",
			user_id="user123",
			expires_at=time.time() + 3600,
			supabase_url="http://supabase",
			supabase_key="key",
		)
		
		save_auth_session(session, api_url)
		loaded = load_auth_session(api_url)
		
		assert loaded is not None
		assert loaded.access_token == "token"
		assert loaded.refresh_token == "refresh"
		assert loaded.user_id == "user123"
		assert get_auth_session_path(api_url).exists()
	
	def test_get_cached_session_refreshes_expired(self, tmp_path, monkeypatch):
		from deadtrees_upload.auth import AuthSession, save_auth_session, get_cached_session, load_auth_session
		
		monkeypatch.setenv("DEADTREES_UPLOAD_CACHE_DIR", str(tmp_path))
		api_url = "http://api.example.com"
		
		session = AuthSession(
			access_token="old_token",
			refresh_token="refresh",
			user_id="user123",
			expires_at=time.time() - 10,
			supabase_url="http://supabase",
			supabase_key="key",
		)
		save_auth_session(session, api_url)
		
		called = {"refreshed": False}
		
		def fake_refresh(self):
			called["refreshed"] = True
			self.access_token = "new_token"
			self.refresh_token = "new_refresh"
			self.expires_at = time.time() + 3600
		
		monkeypatch.setattr(AuthSession, "refresh", fake_refresh, raising=True)
		
		cached = get_cached_session(api_url)
		assert cached is not None
		assert cached.access_token == "new_token"
		assert called["refreshed"]
		
		loaded = load_auth_session(api_url)
		assert loaded is not None
		assert loaded.access_token == "new_token"
	
	def test_get_cached_session_returns_none_on_refresh_error(self, tmp_path, monkeypatch):
		from deadtrees_upload.auth import AuthSession, save_auth_session, get_cached_session, AuthError
		
		monkeypatch.setenv("DEADTREES_UPLOAD_CACHE_DIR", str(tmp_path))
		api_url = "http://api.example.com"
		
		session = AuthSession(
			access_token="old_token",
			refresh_token="refresh",
			user_id="user123",
			expires_at=time.time() - 10,
			supabase_url="http://supabase",
			supabase_key="key",
		)
		save_auth_session(session, api_url)
		
		def fake_refresh(self):
			raise AuthError("refresh failed")
		
		monkeypatch.setattr(AuthSession, "refresh", fake_refresh, raising=True)
		
		cached = get_cached_session(api_url)
		assert cached is None


# =============================================================================
# GEOTIFF VALIDATION (validate_geotiff.py)
# =============================================================================

class TestGeoTIFFValidation:
	"""Tests for GeoTIFF file validation."""
	
	def test_validate_geotiff_valid_file(self):
		from deadtrees_upload.validate_geotiff import validate_geotiff
		
		result, extracted_date = validate_geotiff(FIXTURES_DIR / "test_with_date.tif")
		
		assert result.is_valid
		assert len(result.errors) == 0
	
	def test_validate_geotiff_nonexistent(self):
		from deadtrees_upload.validate_geotiff import validate_geotiff
		
		result, _ = validate_geotiff(Path("/nonexistent/file.tif"))
		
		assert not result.is_valid
		assert "does not exist" in result.errors[0].lower()
	
	def test_validate_geotiff_empty_file(self):
		from deadtrees_upload.validate_geotiff import validate_geotiff
		
		with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as f:
			temp_path = Path(f.name)
		
		try:
			result, _ = validate_geotiff(temp_path)
			assert not result.is_valid
			assert "empty" in result.errors[0].lower()
		finally:
			temp_path.unlink()
	
	def test_extract_date_from_geotiff_with_date(self):
		from deadtrees_upload.validate_geotiff import extract_date_from_geotiff
		
		year, month, day = extract_date_from_geotiff(FIXTURES_DIR / "test_with_date.tif")
		
		assert year == 2024
		assert month == 6
		assert day == 15
	
	def test_extract_date_from_geotiff_no_date(self):
		from deadtrees_upload.validate_geotiff import extract_date_from_geotiff
		
		year, month, day = extract_date_from_geotiff(FIXTURES_DIR / "test_no_date.tif")
		
		assert year is None
		assert month is None
		assert day is None


# =============================================================================
# ZIP VALIDATION (validate_zip.py)
# =============================================================================

class TestZIPValidation:
	"""Tests for ZIP file validation."""
	
	def test_validate_zip_with_images(self):
		from deadtrees_upload.validate_zip import validate_zip
		
		result = validate_zip(FIXTURES_DIR / "test_images_with_exif.zip")
		assert result.is_valid
	
	def test_validate_zip_with_images_tmp(self, tmp_path):
		from deadtrees_upload.validate_zip import validate_zip
		
		zip_path = tmp_path / "images.zip"
		with zipfile.ZipFile(zip_path, 'w') as zf:
			zf.writestr("image1.jpg", b"fake image data")
			zf.writestr("image2.jpg", b"fake image data")
			zf.writestr("image3.jpg", b"fake image data")
		
		result = validate_zip(zip_path)
		assert result.is_valid
		assert len(result.errors) == 0
	
	def test_validate_zip_empty(self, tmp_path):
		from deadtrees_upload.validate_zip import validate_zip
		
		zip_path = tmp_path / "empty.zip"
		with zipfile.ZipFile(zip_path, 'w') as zf:
			pass
		
		result = validate_zip(zip_path)
		assert not result.is_valid
		assert "empty" in result.errors[0].lower()
	
	def test_validate_zip_no_images(self, tmp_path):
		from deadtrees_upload.validate_zip import validate_zip
		
		zip_path = tmp_path / "noimage.zip"
		with zipfile.ZipFile(zip_path, 'w') as zf:
			zf.writestr("readme.txt", b"text content")
			zf.writestr("data.csv", b"csv content")
		
		result = validate_zip(zip_path)
		assert not result.is_valid
		assert "no image" in result.errors[0].lower()
	
	def test_extract_date_from_zip_with_exif(self):
		from deadtrees_upload.validate_zip import extract_date_from_zip
		
		year, month, day = extract_date_from_zip(FIXTURES_DIR / "test_images_with_exif.zip")
		
		assert year == 2024
		assert month == 7
		assert day == 1
	
	def test_extract_date_from_zip_no_exif(self):
		from deadtrees_upload.validate_zip import extract_date_from_zip
		
		year, month, day = extract_date_from_zip(FIXTURES_DIR / "test_images_no_exif.zip")
		
		assert year is None


# =============================================================================
# VALIDATION - FILE DISCOVERY (validation.py)
# =============================================================================

class TestFileDiscovery:
	"""Tests for file discovery and matching."""
	
	def test_find_uploadable_files_directory(self):
		from deadtrees_upload.validation import find_uploadable_files
		
		files, file_types = find_uploadable_files(FIXTURES_DIR)
		
		assert len(files) >= 5
		assert any(f.name == "test_with_date.tif" for f in files)
		assert any(f.name == "test_images_with_exif.zip" for f in files)
	
	def test_find_uploadable_files_geotiff(self, tmp_path):
		from deadtrees_upload.validation import find_uploadable_files
		
		(tmp_path / "test1.tif").touch()
		(tmp_path / "test2.tiff").touch()
		(tmp_path / "readme.txt").touch()
		
		files, file_types = find_uploadable_files(tmp_path)
		
		assert len(files) == 2
		assert all(f.suffix.lower() in [".tif", ".tiff"] for f in files)
		assert file_types["test1.tif"] == "GeoTIFF"
		assert file_types["test2.tiff"] == "GeoTIFF"
	
	def test_find_uploadable_files_zip(self, tmp_path):
		from deadtrees_upload.validation import find_uploadable_files
		
		(tmp_path / "images.zip").touch()
		(tmp_path / "data.zip").touch()
		
		files, file_types = find_uploadable_files(tmp_path)
		
		assert len(files) == 2
		assert file_types["images.zip"] == "ZIP"
	
	def test_find_uploadable_files_mixed(self, tmp_path):
		from deadtrees_upload.validation import find_uploadable_files
		
		(tmp_path / "ortho.tif").touch()
		(tmp_path / "raw.zip").touch()
		(tmp_path / "notes.txt").touch()
		
		files, file_types = find_uploadable_files(tmp_path)
		
		assert len(files) == 2
		assert file_types["ortho.tif"] == "GeoTIFF"
		assert file_types["raw.zip"] == "ZIP"
	
	def test_find_uploadable_files_single_tif(self):
		from deadtrees_upload.validation import find_uploadable_files
		
		single_file = FIXTURES_DIR / "test_with_date.tif"
		files, file_types = find_uploadable_files(single_file)
		
		assert len(files) == 1
		assert files[0] == single_file
		assert file_types[single_file.name] == "GeoTIFF"
	
	def test_find_uploadable_files_single_zip(self):
		from deadtrees_upload.validation import find_uploadable_files
		
		single_file = FIXTURES_DIR / "test_images_with_exif.zip"
		files, file_types = find_uploadable_files(single_file)
		
		assert len(files) == 1
		assert file_types[single_file.name] == "ZIP"
	
	def test_find_uploadable_files_invalid_extension(self):
		from deadtrees_upload.validation import find_uploadable_files, ValidationError
		
		with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
			temp_path = Path(f.name)
		
		try:
			with pytest.raises(ValidationError) as exc_info:
				find_uploadable_files(temp_path)
			assert "not supported" in str(exc_info.value).lower()
		finally:
			temp_path.unlink()
	
	def test_detect_upload_type(self):
		from deadtrees_upload.validation import detect_upload_type
		from deadtrees_upload.models import UploadType
		
		assert detect_upload_type(Path("test.tif")) == UploadType.geotiff
		assert detect_upload_type(Path("test.tiff")) == UploadType.geotiff
		assert detect_upload_type(Path("test.zip")) == UploadType.raw_images_zip
	
	def test_match_files_to_metadata(self, tmp_path):
		from deadtrees_upload.validation import match_files_to_metadata
		from deadtrees_upload.models import FileMetadata, LicenseEnum, PlatformEnum
		
		file1 = tmp_path / "ortho_001.tif"
		file2 = tmp_path / "ortho_002.tif"
		file1.touch()
		file2.touch()
		
		metadata = [
			FileMetadata(
				filename="ortho_001.tif",
				license=LicenseEnum.cc_by,
				platform=PlatformEnum.drone,
				authors=["Test"],
				acquisition_year=2024,
			),
			FileMetadata(
				filename="ortho_002.tif",
				license=LicenseEnum.cc_by,
				platform=PlatformEnum.drone,
				authors=["Test"],
				acquisition_year=2024,
			),
		]
		
		matched, unmatched_files, unmatched_metadata = match_files_to_metadata(
			[file1, file2],
			metadata,
		)
		
		assert len(matched) == 2
		assert len(unmatched_files) == 0
		assert len(unmatched_metadata) == 0
	
	def test_match_files_case_insensitive(self, tmp_path):
		from deadtrees_upload.validation import match_files_to_metadata
		from deadtrees_upload.models import FileMetadata, LicenseEnum, PlatformEnum
		
		file1 = tmp_path / "ORTHO_001.TIF"
		file1.touch()
		
		metadata = [
			FileMetadata(
				filename="ortho_001.tif",
				license=LicenseEnum.cc_by,
				platform=PlatformEnum.drone,
				authors=["Test"],
				acquisition_year=2024,
			),
		]
		
		matched, _, _ = match_files_to_metadata([file1], metadata)
		assert len(matched) == 1
	
	def test_match_files_unmatched(self, tmp_path):
		from deadtrees_upload.validation import match_files_to_metadata
		from deadtrees_upload.models import FileMetadata, LicenseEnum, PlatformEnum
		
		file1 = tmp_path / "ortho_001.tif"
		file2 = tmp_path / "ortho_003.tif"
		file1.touch()
		file2.touch()
		
		metadata = [
			FileMetadata(
				filename="ortho_001.tif",
				license=LicenseEnum.cc_by,
				platform=PlatformEnum.drone,
				authors=["Test"],
				acquisition_year=2024,
			),
			FileMetadata(
				filename="ortho_002.tif",
				license=LicenseEnum.cc_by,
				platform=PlatformEnum.drone,
				authors=["Test"],
				acquisition_year=2024,
			),
		]
		
		matched, unmatched_files, unmatched_metadata = match_files_to_metadata(
			[file1, file2],
			metadata,
		)
		
		assert len(matched) == 1
		assert "ortho_003.tif" in unmatched_files
		assert "ortho_002.tif" in unmatched_metadata


# =============================================================================
# TEMPLATE WIZARD (template.py)
# =============================================================================

class TestTemplateWizard:
	"""Tests for template creation wizard."""
	
	def test_scan_files_with_dates(self):
		from deadtrees_upload.template import scan_files_with_dates
		
		file_infos = scan_files_with_dates(FIXTURES_DIR)
		
		assert len(file_infos) >= 5
		
		with_date = next((f for f in file_infos if f.filename == "test_with_date.tif"), None)
		no_date = next((f for f in file_infos if f.filename == "test_no_date.tif"), None)
		zip_with = next((f for f in file_infos if f.filename == "test_images_with_exif.zip"), None)
		
		assert with_date is not None
		assert with_date.detected_year == 2024
		assert with_date.detected_month == 6
		
		assert no_date is not None
		assert no_date.detected_year is None
		
		assert zip_with is not None
		assert zip_with.detected_year == 2024
	
	def test_parse_date_input(self):
		from deadtrees_upload.template import parse_date_input
		
		assert parse_date_input("2024-06-15") == (2024, 6, 15)
		assert parse_date_input("2024-06") == (2024, 6, None)
		assert parse_date_input("2024") == (2024, None, None)
		assert parse_date_input("invalid") == (None, None, None)
		assert parse_date_input("") == (None, None, None)
	
	def test_format_date(self):
		from deadtrees_upload.template import format_date
		
		assert format_date(2024, 6, 15) == "2024-06-15"
		assert format_date(2024, 6, None) == "2024-06"
		assert format_date(2024, None, None) == "2024"
		assert format_date(None, None, None) == "-"
	
	def test_create_template_dataframe(self):
		from deadtrees_upload.template import FileInfo, create_template_dataframe
		
		file_infos = [
			FileInfo(
				filename="test.tif",
				file_path=Path("test.tif"),
				file_type="GeoTIFF",
				confirmed_year=2024,
				confirmed_month=6,
				confirmed_day=15,
			),
		]
		
		global_values = {
			"license": "CC BY",
			"platform": "drone",
			"authors": "Author",
			"data_access": "public",
		}
		
		df = create_template_dataframe(file_infos, global_values)
		
		assert len(df) == 1
		assert df.iloc[0]["filename"] == "test.tif"
		assert df.iloc[0]["license"] == "CC BY"
		assert df.iloc[0]["acquisition_year"] == 2024


# Run with: pytest tests/test_all.py -v
if __name__ == "__main__":
	pytest.main([__file__, "-v"])
