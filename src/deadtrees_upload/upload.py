"""Sequential chunks for an API whose append/finalization operations are not idempotent."""
import uuid
import hashlib
from typing import Optional, Union

import httpx
from rich.progress import Progress, TaskID

from .models import FileMetadata, UploadResult
from .auth import AuthSession


class UploadError(Exception):
    pass


DEFAULT_CHUNK_SIZE = 100 * 1024 * 1024


def format_size(size_bytes: int) -> str:
    for suffix, scale in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if size_bytes >= scale:
            return f"{size_bytes / scale:.1f} {suffix}"
    return f"{size_bytes} B"


def upload_file(metadata: FileMetadata, token: Union[str, AuthSession], api_url: str,
                chunk_size: int = DEFAULT_CHUNK_SIZE, progress: Optional[Progress] = None,
                task_id: Optional[TaskID] = None, max_retries: int = 3,
                upload_id: Optional[str] = None, expected_sha256: Optional[str] = None) -> UploadResult:
    """Retry only 401 responses known to occur before the server writes a chunk.

    Transport errors and other responses may occur after append or dataset creation.
    Preserve upload_id and return outcome_unknown instead of sending the chunk twice.
    max_retries bounds authentication retries, not replay of uncertain writes.
    """
    upload_id = upload_id or str(uuid.uuid4())

    def failed(message, unknown=False):
        return UploadResult(filename=metadata.filename, success=False, error=message,
                            upload_id=upload_id, outcome_unknown=unknown)

    if metadata.file_path is None or not metadata.file_path.is_file():
        return failed("File does not exist")
    size = metadata.file_path.stat().st_size
    if size == 0 or chunk_size <= 0 or max_retries < 1:
        return failed("Empty file or invalid chunk/retry configuration")
    chunks = (size + chunk_size - 1) // chunk_size
    form = {"upload_id": upload_id, "license": metadata.license.value,
            "platform": metadata.platform.value, "authors": metadata.authors,
            "data_access": metadata.data_access.value, "chunks_total": str(chunks)}
    for source, target in (("acquisition_year", "aquisition_year"), ("acquisition_month", "aquisition_month"),
                           ("acquisition_day", "aquisition_day"), ("additional_information", "additional_information"),
                           ("citation_doi", "citation_doi")):
        value = getattr(metadata, source)
        if value is not None:
            form[target] = str(value)
    if metadata.upload_type:
        form["upload_type"] = metadata.upload_type.value
    attempted = False
    transmitted_hash = hashlib.sha256()
    try:
        with metadata.file_path.open("rb") as stream, httpx.Client(timeout=300) as client:
            for index in range(chunks):
                data = stream.read(chunk_size)
                if not data:
                    return failed("File changed during upload; reconcile before retry", attempted)
                transmitted_hash.update(data)
                if index == chunks - 1 and (stream.read(1) or
                        (expected_sha256 and transmitted_hash.hexdigest() != expected_sha256)):
                    return failed("File changed after validation; final chunk not sent. Reconcile any partial upload", attempted)
                for attempt in range(max_retries):
                    bearer = token.get_valid_token() if isinstance(token, AuthSession) else token
                    attempted = True
                    response = client.post(api_url.rstrip("/") + "/datasets/chunk",
                                           data={**form, "chunk_index": str(index)},
                                           files={"file": (metadata.file_path.name, data, "application/octet-stream")},
                                           headers={"Authorization": f"Bearer {bearer}"})
                    if response.status_code == 401:
                        if isinstance(token, AuthSession) and attempt + 1 < max_retries:
                            token.refresh()
                            continue
                        return failed("Authentication rejected; earlier chunks may remain on the server" if index else "Authentication rejected before any chunk was accepted", index > 0)
                    break
                if response.status_code >= 300:
                    return failed(f"Upload stopped at chunk {index + 1}/{chunks} (HTTP {response.status_code}); reconcile before retry", True)
                if progress and task_id is not None:
                    progress.update(task_id, completed=min((index + 1) * chunk_size, size))
                if index == chunks - 1:
                    dataset_id = response.json().get("id")
                    if type(dataset_id) is not int or dataset_id <= 0:
                        return failed("Final response lacks a valid dataset ID; reconcile before retry", True)
                    return UploadResult(filename=metadata.filename, success=True, dataset_id=dataset_id, upload_id=upload_id)
    except Exception:
        # Avoid server bodies, request URLs, and exception strings that can contain secrets.
        return failed("Upload interrupted; inspect the upload receipt before any retry", attempted)
    return failed("Upload ended without a confirmed dataset", attempted)


from .process import trigger_processing  # noqa: E402,F401
