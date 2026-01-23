"""Chunked upload logic for datasets."""

import uuid
from pathlib import Path
from typing import Optional, Union

import httpx
from rich.progress import Progress, TaskID

from .models import FileMetadata, UploadResult
from .auth import AuthSession


class UploadError(Exception):
	"""Upload error."""
	pass


# Default chunk size: 100MB
DEFAULT_CHUNK_SIZE = 100 * 1024 * 1024


def format_size(size_bytes: int) -> str:
	"""Format file size in human-readable format."""
	if size_bytes < 1024:
		return f"{size_bytes} B"
	elif size_bytes < 1024 ** 2:
		return f"{size_bytes / 1024:.1f} KB"
	elif size_bytes < 1024 ** 3:
		return f"{size_bytes / (1024 ** 2):.1f} MB"
	else:
		return f"{size_bytes / (1024 ** 3):.2f} GB"


def upload_file(
	metadata: FileMetadata,
	token: Union[str, AuthSession],
	api_url: str,
	chunk_size: int = DEFAULT_CHUNK_SIZE,
	progress: Optional[Progress] = None,
	task_id: Optional[TaskID] = None,
	max_retries: int = 3,
) -> UploadResult:
	"""
	Upload a single file with chunked upload.
	
	Supports automatic token refresh when using AuthSession.
	
	Args:
		metadata: File metadata including file_path
		token: Authentication token (string) or AuthSession (with refresh)
		api_url: Base API URL
		chunk_size: Size of each chunk in bytes
		progress: Optional Rich Progress instance for updates
		task_id: Optional task ID for progress updates
		max_retries: Maximum retries per chunk on failure
	
	Returns:
		UploadResult with success status and dataset ID
	"""
	if metadata.file_path is None:
		return UploadResult(
			filename=metadata.filename,
			success=False,
			error="No file path set",
		)
	
	file_path = metadata.file_path
	
	if not file_path.exists():
		return UploadResult(
			filename=metadata.filename,
			success=False,
			error="File does not exist",
		)
	
	file_size = file_path.stat().st_size
	chunks_total = (file_size + chunk_size - 1) // chunk_size
	upload_id = str(uuid.uuid4())
	
	# Determine upload endpoint
	upload_url = api_url.rstrip("/") + "/datasets/chunk"
	
	# Prepare form data (constant across chunks)
	base_form_data = {
		"upload_id": upload_id,
		"license": metadata.license.value,
		"platform": metadata.platform.value,
		"authors": [author for author in metadata.authors],
		"data_access": metadata.data_access.value,
	}
	
	# Add optional fields
	if metadata.acquisition_year is not None:
		base_form_data["aquisition_year"] = str(metadata.acquisition_year)
	if metadata.acquisition_month is not None:
		base_form_data["aquisition_month"] = str(metadata.acquisition_month)
	if metadata.acquisition_day is not None:
		base_form_data["aquisition_day"] = str(metadata.acquisition_day)
	if metadata.additional_information:
		base_form_data["additional_information"] = metadata.additional_information
	if metadata.citation_doi:
		base_form_data["citation_doi"] = metadata.citation_doi
	
	# Add upload type
	if metadata.upload_type:
		base_form_data["upload_type"] = metadata.upload_type.value
	
	def get_token() -> str:
		"""Get current valid token, refreshing if needed."""
		if isinstance(token, AuthSession):
			return token.get_valid_token()
		return token
	
	try:
		with open(file_path, "rb") as f, httpx.Client(timeout=httpx.Timeout(timeout=300.0)) as client:
			bytes_uploaded = 0
			
			for chunk_index in range(chunks_total):
				chunk_data = f.read(chunk_size)
				
				# Prepare form data for this chunk
				form_data = {
					**base_form_data,
					"chunk_index": str(chunk_index),
					"chunks_total": str(chunks_total),
				}
				
				# Prepare file upload
				files = {
					"file": (file_path.name, chunk_data, "application/octet-stream"),
				}
				
				# Retry loop for this chunk
				last_error = None
				for retry in range(max_retries):
					try:
						# Get fresh token (may refresh if expired)
						current_token = get_token()
						
						# Send chunk
						response = client.post(
							upload_url,
							data=form_data,
							files=files,
							headers={"Authorization": f"Bearer {current_token}"},
						)
						
						# Handle 401 - try token refresh
						if response.status_code == 401:
							if isinstance(token, AuthSession):
								try:
									token.refresh()
									continue  # Retry with new token
								except Exception:
									pass
							return UploadResult(
								filename=metadata.filename,
								success=False,
								error="Authentication failed - please re-login",
							)
						
						if response.status_code >= 400:
							error_detail = response.text
							try:
								error_detail = response.json().get("detail", response.text)
							except Exception:
								pass
							last_error = f"Upload failed (chunk {chunk_index + 1}/{chunks_total}): {error_detail}"
							continue  # Retry
						
						response.raise_for_status()
						
						# Success - break retry loop
						last_error = None
						break
						
					except httpx.TimeoutException:
						last_error = f"Timeout on chunk {chunk_index + 1}/{chunks_total}"
						continue  # Retry
					except httpx.ConnectError:
						last_error = f"Connection error on chunk {chunk_index + 1}/{chunks_total}"
						continue  # Retry
				
				# If all retries failed
				if last_error:
					return UploadResult(
						filename=metadata.filename,
						success=False,
						error=last_error,
					)
				
				# Update progress
				bytes_uploaded += len(chunk_data)
				if progress and task_id is not None:
					progress.update(task_id, completed=bytes_uploaded)
				
				# On final chunk, get dataset info
				if chunk_index == chunks_total - 1:
					result_data = response.json()
					dataset_id = result_data.get("id")
					
					return UploadResult(
						filename=metadata.filename,
						success=True,
						dataset_id=dataset_id,
					)
		
		# Should not reach here
		return UploadResult(
			filename=metadata.filename,
			success=False,
			error="Upload completed but no response received",
		)
		
	except httpx.ConnectError:
		return UploadResult(
			filename=metadata.filename,
			success=False,
			error=f"Could not connect to {upload_url}",
		)
	except httpx.TimeoutException:
		return UploadResult(
			filename=metadata.filename,
			success=False,
			error="Upload timed out",
		)
	except Exception as e:
		return UploadResult(
			filename=metadata.filename,
			success=False,
			error=f"Upload error: {str(e)}",
		)


# Re-export trigger_processing for backward compatibility
from .process import trigger_processing  # noqa: E402, F401
