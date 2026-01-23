"""Duplicate detection and upload session management."""

import json
import hashlib
from pathlib import Path
from typing import Optional, Dict, List, Set
from dataclasses import dataclass, field, asdict
from datetime import datetime

import httpx


class DedupError(Exception):
	"""Duplicate detection error."""
	pass


def get_file_identifier(file_path: Path, sample_size: int = 10 * 1024 * 1024) -> str:
	"""
	Generate a quick file identifier by sampling start/end of file.
	
	This matches the backend's hash calculation in shared/hash.py.
	
	Args:
		file_path: Path to file
		sample_size: Size of samples to read (default 10MB)
	
	Returns:
		SHA256 hex digest
	"""
	file_size = file_path.stat().st_size
	hasher = hashlib.sha256()
	
	with open(file_path, 'rb') as f:
		# Hash file size
		hasher.update(str(file_size).encode())
		
		# Hash first 10MB
		hasher.update(f.read(sample_size))
		
		# Hash last 10MB
		if file_size > sample_size:
			f.seek(-min(sample_size, file_size), 2)
			hasher.update(f.read(sample_size))
	
	return hasher.hexdigest()


def check_hash_exists(file_hash: str, api_url: str, token: str) -> Optional[int]:
	"""
	Check if a file hash already exists in the database.
	
	Args:
		file_hash: SHA256 hash to check
		api_url: Base API URL
		token: Authentication token
	
	Returns:
		Dataset ID if exists, None otherwise
	"""
	# Query the API to check for existing hash
	# This would require an endpoint on the backend
	# For now, we'll implement a fallback using filename matching
	
	# TODO: Implement API endpoint for hash check
	# check_url = api_url.rstrip("/") + "/datasets/check-hash"
	# response = client.post(check_url, json={"sha256": file_hash}, headers=...)
	
	return None


@dataclass
class UploadSessionState:
	"""State of an upload session for resume capability."""
	session_id: str
	created_at: str
	data_directory: str
	metadata_file: str
	api_url: str
	
	# File tracking
	files_total: int = 0
	files_completed: List[str] = field(default_factory=list)
	files_failed: Dict[str, str] = field(default_factory=dict)  # filename -> error
	files_skipped: Dict[str, str] = field(default_factory=dict)  # filename -> reason
	
	# Hash cache for duplicate detection
	file_hashes: Dict[str, str] = field(default_factory=dict)  # filename -> hash
	
	# Results
	dataset_ids: Dict[str, int] = field(default_factory=dict)  # filename -> dataset_id
	
	@property
	def files_pending(self) -> int:
		"""Count of files not yet processed."""
		processed = len(self.files_completed) + len(self.files_failed) + len(self.files_skipped)
		return self.files_total - processed
	
	@property
	def is_complete(self) -> bool:
		"""Check if all files have been processed."""
		return self.files_pending == 0
	
	def mark_completed(self, filename: str, dataset_id: int) -> None:
		"""Mark a file as successfully uploaded."""
		self.files_completed.append(filename)
		self.dataset_ids[filename] = dataset_id
		# Remove from failed if it was retried
		self.files_failed.pop(filename, None)
	
	def mark_failed(self, filename: str, error: str) -> None:
		"""Mark a file as failed."""
		self.files_failed[filename] = error
	
	def mark_skipped(self, filename: str, reason: str) -> None:
		"""Mark a file as skipped (e.g., duplicate)."""
		self.files_skipped[filename] = reason
	
	def should_process(self, filename: str) -> bool:
		"""Check if a file should be processed (not already completed or skipped)."""
		return filename not in self.files_completed and filename not in self.files_skipped
	
	def save(self, path: Path) -> None:
		"""Save session state to file."""
		with open(path, 'w') as f:
			json.dump(asdict(self), f, indent=2)
	
	@classmethod
	def load(cls, path: Path) -> 'UploadSessionState':
		"""Load session state from file."""
		with open(path, 'r') as f:
			data = json.load(f)
		return cls(**data)
	
	@classmethod
	def create(cls, data_directory: str, metadata_file: str, api_url: str) -> 'UploadSessionState':
		"""Create a new session state."""
		import uuid
		return cls(
			session_id=str(uuid.uuid4())[:8],
			created_at=datetime.now().isoformat(),
			data_directory=data_directory,
			metadata_file=metadata_file,
			api_url=api_url,
		)


def get_session_file_path(data_directory: Path) -> Path:
	"""Get the path to the session state file."""
	return data_directory / ".deadtrees-upload-session.json"


def find_existing_session(data_directory: Path) -> Optional[UploadSessionState]:
	"""
	Find an existing upload session for a directory.
	
	Args:
		data_directory: Directory to check
	
	Returns:
		UploadSessionState if found, None otherwise
	"""
	session_file = get_session_file_path(data_directory)
	
	if session_file.exists():
		try:
			return UploadSessionState.load(session_file)
		except Exception:
			return None
	
	return None


def calculate_file_hashes(
	files: List[Path],
	existing_hashes: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
	"""
	Calculate hashes for files, using cached values where available.
	
	Args:
		files: List of file paths
		existing_hashes: Previously calculated hashes
	
	Returns:
		Dict of filename -> hash
	"""
	hashes = existing_hashes.copy() if existing_hashes else {}
	
	for file_path in files:
		filename = file_path.name
		if filename not in hashes:
			try:
				hashes[filename] = get_file_identifier(file_path)
			except Exception:
				pass  # Skip files that can't be hashed
	
	return hashes


def find_duplicates_by_hash(
	file_hashes: Dict[str, str],
	known_hashes: Set[str],
) -> Dict[str, str]:
	"""
	Find files that are duplicates based on hash.
	
	Args:
		file_hashes: Dict of filename -> hash
		known_hashes: Set of hashes already in database
	
	Returns:
		Dict of filename -> "duplicate" for duplicates
	"""
	duplicates = {}
	
	for filename, file_hash in file_hashes.items():
		if file_hash in known_hashes:
			duplicates[filename] = f"File already uploaded (hash: {file_hash[:16]}...)"
	
	return duplicates
