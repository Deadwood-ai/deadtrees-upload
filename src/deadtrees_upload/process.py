"""Processing pipeline trigger logic."""

from typing import Union, List

import httpx

from .models import UploadType
from .auth import AuthSession


# Processing task types for each upload type
GEOTIFF_PROCESSING_TASKS: List[str] = [
	"cog",
	"thumbnail",
	"metadata",
	"geotiff",
	"deadwood",
	"treecover",
]

RAW_IMAGES_PROCESSING_TASKS: List[str] = [
	"odm_processing",
	"cog",
	"thumbnail",
	"metadata",
	"geotiff",
	"deadwood",
	"treecover",
]


def get_processing_tasks(upload_type: UploadType) -> List[str]:
	"""
	Get the appropriate processing tasks for an upload type.
	
	Args:
		upload_type: Type of upload (geotiff or raw_images_zip)
	
	Returns:
		List of task type strings
	"""
	if upload_type == UploadType.raw_images_zip:
		return RAW_IMAGES_PROCESSING_TASKS
	return GEOTIFF_PROCESSING_TASKS


def trigger_processing(
	dataset_id: int,
	upload_type: UploadType,
	token: Union[str, AuthSession],
	api_url: str,
	priority: int = 4,
) -> bool:
	"""
	Trigger processing pipeline for an uploaded dataset.
	
	Args:
		dataset_id: ID of the uploaded dataset
		upload_type: Type of upload (geotiff or raw_images_zip)
		token: Authentication token or AuthSession
		api_url: Base API URL
		priority: Processing priority (1=highest, 4=default)
	
	Returns:
		True if processing was triggered successfully
	"""
	task_types = get_processing_tasks(upload_type)
	
	# Get token string
	if isinstance(token, AuthSession):
		token_str = token.get_valid_token()
	else:
		token_str = token
	
	process_url = api_url.rstrip("/") + f"/datasets/{dataset_id}/process"
	
	try:
		with httpx.Client(timeout=30.0) as client:
			response = client.put(
				process_url,
				json={"task_types": task_types, "priority": priority},
				headers={
					"Authorization": f"Bearer {token_str}",
					"Content-Type": "application/json",
				},
			)
			
			if response.status_code == 200:
				return True
			else:
				return False
	except Exception:
		return False
