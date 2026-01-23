"""Pydantic models for metadata validation and API requests."""

from enum import Enum
from typing import Optional, List
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class LicenseEnum(str, Enum):
	"""Supported license types for datasets."""
	cc_by = "CC BY"
	cc_by_sa = "CC BY-SA"
	cc_by_nc_sa = "CC BY-NC-SA"
	cc_by_nc = "CC BY-NC"
	mit = "MIT"


class PlatformEnum(str, Enum):
	"""Platform types for data capture. Only drone and airborne supported."""
	drone = "drone"
	airborne = "airborne"


class DataAccessEnum(str, Enum):
	"""Data access levels."""
	public = "public"
	private = "private"
	viewonly = "viewonly"


class UploadType(str, Enum):
	"""Type of upload based on file format."""
	geotiff = "geotiff"
	raw_images_zip = "raw_images_zip"


class FileMetadata(BaseModel):
	"""Metadata for a single file to upload."""
	
	filename: str = Field(..., description="Name of the file (must match actual file)")
	license: LicenseEnum = Field(..., description="License for the dataset")
	platform: PlatformEnum = Field(..., description="Platform used for capture")
	authors: List[str] = Field(..., description="List of author names")
	
	# Optional fields
	acquisition_year: Optional[int] = Field(None, ge=1980, le=2099)
	acquisition_month: Optional[int] = Field(None, ge=1, le=12)
	acquisition_day: Optional[int] = Field(None, ge=1, le=31)
	data_access: DataAccessEnum = Field(default=DataAccessEnum.public)
	additional_information: Optional[str] = Field(None)
	citation_doi: Optional[str] = Field(None)
	
	# Runtime fields (not from metadata file)
	file_path: Optional[Path] = Field(None, exclude=True)
	upload_type: Optional[UploadType] = Field(None, exclude=True)
	
	@field_validator("authors", mode="before")
	@classmethod
	def parse_authors(cls, v):
		"""Parse authors from semicolon-separated string or list."""
		if isinstance(v, str):
			# Split by semicolon and strip whitespace
			return [author.strip() for author in v.split(";") if author.strip()]
		return v
	
	@field_validator("license", mode="before")
	@classmethod
	def normalize_license(cls, v):
		"""Normalize license string to enum value."""
		if isinstance(v, str):
			# Try exact match first
			v_upper = v.upper().strip()
			for license_type in LicenseEnum:
				if license_type.value.upper() == v_upper:
					return license_type
			# Try without spaces
			v_no_space = v_upper.replace(" ", "").replace("-", "")
			for license_type in LicenseEnum:
				if license_type.value.upper().replace(" ", "").replace("-", "") == v_no_space:
					return license_type
		return v
	
	@field_validator("platform", mode="before")
	@classmethod
	def normalize_platform(cls, v):
		"""Normalize platform string to enum value."""
		if isinstance(v, str):
			return v.lower().strip()
		return v
	
	@field_validator("data_access", mode="before")
	@classmethod
	def normalize_data_access(cls, v):
		"""Normalize data_access string to enum value."""
		if isinstance(v, str):
			return v.lower().strip()
		if v is None:
			return DataAccessEnum.public
		return v


class ValidationResult(BaseModel):
	"""Result of validating a file."""
	
	filename: str
	is_valid: bool
	warnings: List[str] = Field(default_factory=list)
	errors: List[str] = Field(default_factory=list)
	metadata: Optional[FileMetadata] = None


class UploadResult(BaseModel):
	"""Result of uploading a file."""
	
	filename: str
	success: bool
	dataset_id: Optional[int] = None
	error: Optional[str] = None


class UploadSession(BaseModel):
	"""State of an upload session."""
	
	data_dir: Path
	metadata_file: Path
	files: List[FileMetadata]
	validation_results: List[ValidationResult] = Field(default_factory=list)
	upload_results: List[UploadResult] = Field(default_factory=list)
	api_url: str
	dry_run: bool = False
