"""Chunked upload that continues an interrupted upload instead of starting again.

The chunk API keeps a durable receipt per chunk (deadtrees repo,
docs/playbooks/upload-retry-contract.md): an identical repeated chunk is
acknowledged without writing twice, and `GET /datasets/uploads/{upload_id}` reports
which chunks arrived. So a failed request is retried, and a later run with the same
upload ID continues after the chunks the server holds.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
import uuid
import hashlib
from typing import Optional, Union

import httpx
from rich.progress import Progress, TaskID

from .models import FileMetadata, UploadResult
from .auth import AuthSession
from .dedup import RemoteDuplicate


class UploadError(Exception):
    pass


DEFAULT_CHUNK_SIZE = 100 * 1024 * 1024
DUPLICATE_UPLOAD_CODE = "DUPLICATE_UPLOAD"
# Network errors and these replies are retried; the server answers a repeated chunk idempotently.
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
CHUNK_ATTEMPTS = 8
# Chunks in flight at once; the server places each at index * chunk_size.
PARALLEL_CHUNKS = 3
_sleep = time.sleep


def rejected_as_duplicate(response: httpx.Response) -> Optional[RemoteDuplicate]:
    """The API's HTTP 409 for a file already on the platform; no dataset was created."""
    if response.status_code != 409:
        return None
    try:
        detail = response.json().get("detail")
    except ValueError:
        return None
    if not isinstance(detail, dict) or detail.get("code") != DUPLICATE_UPLOAD_CODE:
        return None
    dataset_id = detail.get("existing_dataset_id")
    message = detail.get("message")
    return RemoteDuplicate(dataset_id=dataset_id if type(dataset_id) is int else None,
                           message=message if isinstance(message, str) else "")


def format_size(size_bytes: int) -> str:
    for suffix, scale in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if size_bytes >= scale:
            return f"{size_bytes / scale:.1f} {suffix}"
    return f"{size_bytes} B"


def _server_status(client: httpx.Client, api_url: str, upload_id: str, bearer: str) -> Optional[dict]:
    """The server's view of an upload, or None when it holds nothing under this ID."""
    response = client.get(f"{api_url.rstrip('/')}/datasets/uploads/{upload_id}",
                          headers={"Authorization": f"Bearer {bearer}"})
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise UploadError(f"Upload status unavailable (HTTP {response.status_code})")
    return response.json()


def upload_file(metadata: FileMetadata, token: Union[str, AuthSession], api_url: str,
                chunk_size: int = DEFAULT_CHUNK_SIZE, progress: Optional[Progress] = None,
                task_id: Optional[TaskID] = None, max_retries: int = 3,
                upload_id: Optional[str] = None, expected_sha256: Optional[str] = None,
                allow_duplicate: bool = False, resume: bool = False) -> UploadResult:
    """Upload a file under `upload_id`, continuing after the chunks the server holds when `resume` is set.

    A resume first compares every received chunk with this file, so it never appends
    one file's bytes to another's. Each chunk is retried on network errors and busy or
    server errors (CHUNK_ATTEMPTS), and after a rejected login (max_retries refreshes).
    A run that still fails keeps its upload_id with outcome_unknown, so a later
    `resume=True` run continues it.
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
    if allow_duplicate:
        # Explicit override: the platform accepts a file it already holds as a new dataset.
        form["allow_duplicate"] = "true"
    # Declared so the server accepts chunks in any order (several are in flight at once).
    form["chunk_size"] = str(chunk_size)
    bearer = lambda: token.get_valid_token() if isinstance(token, AuthSession) else token  # noqa: E731
    path = metadata.file_path
    url = api_url.rstrip("/") + "/datasets/chunk"
    lock = threading.Lock()
    refreshes = [0]
    # Whether a chunk request went out, and how many chunks the server confirmed:
    # with neither, nothing can be on the server and a retry is safe.
    attempted = [False]
    stored = [0]
    stop = threading.Event()

    class Stopped(Exception):
        """A chunk ended the upload; carries the result to report."""
        def __init__(self, result: UploadResult):
            self.result = result

    def send(client: httpx.Client, index: int) -> httpx.Response:
        """POST one chunk with retries; raise Stopped when the upload cannot go on."""
        with path.open("rb") as stream:
            stream.seek(index * chunk_size)
            data = stream.read(chunk_size)
        if not data:
            raise Stopped(failed("File changed during upload; reconcile before retry", True))
        for attempt in range(1, CHUNK_ATTEMPTS + 1):
            if stop.is_set():
                raise Stopped(failed("Upload stopped", True))
            attempted[0] = True
            try:
                response = client.post(url, data={**form, "chunk_index": str(index)},
                                       files={"file": (path.name, data, "application/octet-stream")},
                                       headers={"Authorization": f"Bearer {bearer()}"})
            except httpx.TransportError:
                response = None
            if response is not None and response.status_code == 401:
                with lock:
                    if isinstance(token, AuthSession) and refreshes[0] + 1 < max_retries:
                        refreshes[0] += 1
                        token.refresh()
                        continue
                raise Stopped(failed("Authentication rejected; run again with --resume after signing in", stored[0] > 0))
            if response is not None and response.status_code not in RETRYABLE_STATUS:
                duplicate = rejected_as_duplicate(response)
                if duplicate:
                    raise Stopped(UploadResult(filename=metadata.filename, success=False, error=duplicate.describe(),
                                               dataset_id=duplicate.dataset_id, upload_id=upload_id, already_on_platform=True))
                if response.status_code >= 300:
                    raise Stopped(failed(f"Upload stopped at chunk {index + 1}/{chunks} (HTTP {response.status_code}); "
                                         "reconcile before retry", True))
                with lock:
                    stored[0] += 1
                    if progress and task_id is not None:
                        progress.advance(task_id, len(data))
                return response
            if attempt < CHUNK_ATTEMPTS:
                _sleep(min(2 ** attempt, 30))
        raise Stopped(failed(f"Upload stopped at chunk {index + 1}/{chunks} after repeated network or server errors; "
                             "run again with --resume to continue", True))

    try:
        with httpx.Client(timeout=300) as client:
            missing = list(range(chunks))
            workers = PARALLEL_CHUNKS
            if resume:
                status = _server_status(client, api_url, upload_id, bearer())
                if status is not None:
                    if status["state"] == "complete" and (status.get("response") or {}).get("id"):
                        return UploadResult(filename=metadata.filename, success=True,
                                            dataset_id=status["response"]["id"], upload_id=upload_id)
                    if status["state"] == "expired":
                        return failed("The unfinished upload expired and its data was removed; upload the file again")
                    contract = status.get("contract") or {}
                    if contract.get("chunk_size") is None:
                        # Started before parallel sending: continue in order, without a chunk size.
                        form.pop("chunk_size")
                        workers = 1
                    if (status["state"] != "receiving" or status.get("chunks_total") != chunks
                            or contract.get("chunk_size") not in (None, chunk_size)):
                        return failed("The unfinished upload cannot be continued; reconcile it before a retry", True)
                    received = status.get("chunks") or []
                    stored[0] = status.get("chunks_received", 0)
                    with path.open("rb") as stream:
                        for index, receipt in enumerate(received):
                            if receipt is None:
                                continue
                            stream.seek(index * chunk_size)
                            data = stream.read(chunk_size)
                            if len(data) != receipt["size"] or hashlib.sha256(data).hexdigest() != receipt["sha256"]:
                                return failed("This file differs from the unfinished upload; nothing was sent", True)
                    missing = [index for index in range(chunks) if index >= len(received) or received[index] is None]
                    if progress and task_id is not None:
                        progress.update(task_id, completed=status.get("bytes_received", 0))
                    # Every chunk arrived but the last reply was lost: send the last chunk again to finish.
                    missing = missing or [chunks - 1]
            # The server finishes the upload when its last missing chunk arrives. That
            # chunk waits until the others are stored and the file is checked unchanged.
            last, others = missing[-1], missing[:-1]
            pool = ThreadPoolExecutor(max_workers=workers)
            try:
                for future in as_completed([pool.submit(send, client, index) for index in others]):
                    future.result()
            except Stopped:
                # The first failure stops the chunks still waiting and those between retries.
                stop.set()
                raise
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
            if path.stat().st_size != size or (expected_sha256 and _file_sha256(path) != expected_sha256):
                return failed("File changed after validation; final chunk not sent. Reconcile any partial upload", attempted[0])
            response = send(client, last)
            dataset_id = response.json().get("id")
            if type(dataset_id) is not int or dataset_id <= 0:
                return failed("Final response lacks a valid dataset ID; reconcile before retry", True)
            return UploadResult(filename=metadata.filename, success=True, dataset_id=dataset_id, upload_id=upload_id)
    except Stopped as stopped:
        return stopped.result
    except Exception:
        # Avoid server bodies, request URLs, and exception strings that can contain secrets.
        return failed("Upload interrupted; run again with --resume to continue", attempted[0])


def _file_sha256(path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


from .process import trigger_processing  # noqa: E402,F401
