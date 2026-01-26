"""ZIP file validation for raw drone images."""

from pathlib import Path
from typing import Set, Tuple, Optional
import zipfile
from datetime import datetime

from .models import ValidationResult


# Supported image extensions in ZIP files
IMAGE_EXTENSIONS: Set[str] = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".dng", ".raw", ".cr2", ".nef", ".arw"}
JPEG_EXTENSIONS: Set[str] = {".jpg", ".jpeg"}


def extract_date_from_zip(file_path: Path) -> Tuple[Optional[int], Optional[int], Optional[int]]:
	"""
	Try to extract acquisition date from JPEG EXIF in a ZIP file.
	
	Samples JPEG images in the ZIP and extracts DateTimeOriginal from EXIF.
	
	Args:
		file_path: Path to ZIP file
	
	Returns:
		Tuple of (year, month, day) - any can be None if not found
	"""
	try:
		import io
		from PIL import Image
		from PIL.ExifTags import TAGS
		
		with zipfile.ZipFile(file_path, 'r') as zf:
			# Find JPEG files
			jpeg_files = [
				f for f in zf.namelist()
				if not f.startswith('__MACOSX') and not f.startswith('.')
				and Path(f).suffix.lower() in JPEG_EXTENSIONS
			]
			
			if not jpeg_files:
				return None, None, None
			
			# Sample first few images
			for img_path in jpeg_files[:3]:
				try:
					with zf.open(img_path) as img_file:
						img = Image.open(io.BytesIO(img_file.read()))
						exif = img._getexif()
						
						if exif:
							for tag_id, value in exif.items():
								tag = TAGS.get(tag_id, tag_id)
								if tag == "DateTimeOriginal":
									# Format: "2024:07:01 10:00:00"
									try:
										dt = datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
										return dt.year, dt.month, dt.day
									except ValueError:
										pass
				except Exception:
					continue
			
			return None, None, None
	except Exception:
		return None, None, None


def check_image_has_gps(zf: zipfile.ZipFile, image_path: str) -> bool:
	"""
	Check if an image in a ZIP has GPS coordinates in EXIF.
	
	Args:
		zf: Open ZipFile object
		image_path: Path to image within ZIP
	
	Returns:
		True if GPS coordinates found
	"""
	try:
		import io
		from PIL import Image
		from PIL.ExifTags import TAGS, GPSTAGS
		
		with zf.open(image_path) as img_file:
			img = Image.open(io.BytesIO(img_file.read()))
			exif = img._getexif()
			
			if exif:
				for tag_id, value in exif.items():
					tag = TAGS.get(tag_id, tag_id)
					if tag == "GPSInfo":
						# Check if GPS has actual coordinates
						gps_data = {}
						for gps_tag_id in value:
							gps_tag = GPSTAGS.get(gps_tag_id, gps_tag_id)
							gps_data[gps_tag] = value[gps_tag_id]
						
						if "GPSLatitude" in gps_data and "GPSLongitude" in gps_data:
							return True
			return False
	except Exception:
		return False


def validate_zip(file_path: Path) -> ValidationResult:
	"""
	Validate a ZIP file containing raw drone images.
	
	Checks:
	- File exists and is not empty
	- ZIP is not corrupted
	- Contains image files
	- Has at least 3 images (ODM minimum)
	- Sample images have GPS coordinates (recommended for ODM)
	
	Args:
		file_path: Path to ZIP file
	
	Returns:
		ValidationResult with any warnings/errors
	"""
	warnings = []
	errors = []
	
	if not file_path.exists():
		return ValidationResult(
			filename=file_path.name,
			is_valid=False,
			errors=["File does not exist"],
		)
	
	# Check file size
	file_size = file_path.stat().st_size
	if file_size == 0:
		return ValidationResult(
			filename=file_path.name,
			is_valid=False,
			errors=["File is empty"],
		)
	
	try:
		with zipfile.ZipFile(file_path, 'r') as zf:
			# Check if ZIP is valid
			bad_file = zf.testzip()
			if bad_file:
				errors.append(f"Corrupted file in ZIP: {bad_file}")
				return ValidationResult(
					filename=file_path.name,
					is_valid=False,
					errors=errors,
				)
			
			# Get list of files
			file_list = zf.namelist()
			
			if not file_list:
				errors.append("ZIP file is empty")
				return ValidationResult(
					filename=file_path.name,
					is_valid=False,
					errors=errors,
				)
			
			# Filter to image files only
			image_files = []
			for name in file_list:
				# Skip directories and hidden files
				if name.endswith('/') or name.startswith('__MACOSX') or name.startswith('.'):
					continue
				
				suffix = Path(name).suffix.lower()
				if suffix in IMAGE_EXTENSIONS:
					image_files.append(name)
			
			if len(image_files) == 0:
				errors.append("No image files found in ZIP")
			elif len(image_files) < 3:
				warnings.append(f"Only {len(image_files)} images found - ODM typically needs at least 3 for reconstruction")
			else:
				# Check GPS coordinates in a sample of JPEG images
				# GPS is critical for ODM to work efficiently
				jpeg_images = [f for f in image_files if Path(f).suffix.lower() in {'.jpg', '.jpeg'}]
				
				if jpeg_images:
					sample_size = min(5, len(jpeg_images))
					sample_images = jpeg_images[:sample_size]
					gps_count = 0
					
					try:
						for img_path in sample_images:
							if check_image_has_gps(zf, img_path):
								gps_count += 1
						
						if gps_count == 0:
							warnings.append(
								"No GPS coordinates found in sample images. "
								"Without GPS data, ODM processing may fail or take extremely long (hours to days). "
								"Consider using images with embedded GPS coordinates."
							)
						elif gps_count < sample_size:
							warnings.append(
								f"Only {gps_count}/{sample_size} sample images have GPS coordinates. "
								"Missing GPS data may affect processing quality."
							)
					except ImportError:
						# PIL not available, skip GPS check
						pass
			
			# Check for nested ZIPs
			nested_zips = [n for n in file_list if n.lower().endswith('.zip')]
			if nested_zips:
				warnings.append(f"Nested ZIP files found: {', '.join(nested_zips[:3])}")
	
	except zipfile.BadZipFile:
		errors.append("Invalid or corrupted ZIP file")
	except Exception as e:
		errors.append(f"Error reading ZIP: {str(e)}")
	
	return ValidationResult(
		filename=file_path.name,
		is_valid=len(errors) == 0,
		warnings=warnings,
		errors=errors,
	)
