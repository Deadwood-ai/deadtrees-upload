"""Offline plans and explicit unattended upload orchestration."""
import hashlib
import json
import os
import uuid
from collections import Counter
from pathlib import Path

import httpx

from .auth import create_auth_session, get_cached_session
from .config import supabase_config, validate_url
from .state import atomic_json
from .metadata import COLUMN_ALIASES, find_column_mapping, parse_metadata, read_metadata_file
from .validation import find_uploadable_files, match_files_to_metadata, validate_all
from .upload import upload_file
from .process import trigger_processing, get_processing_tasks


class BatchError(Exception):
    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


def plan(data_path: Path, metadata_path: Path) -> dict:
    """Read local inputs only. Never authenticate, prompt, or write session state."""
    files, _ = find_uploadable_files(data_path)
    if not files:
        raise BatchError("No uploadable files found (top-level GeoTIFF or ZIP files required)")
    df = read_metadata_file(metadata_path)
    mapping, missing = find_column_mapping(df)
    errors = [f"Missing column: {name}" for name in missing]
    for name, aliases in COLUMN_ALIASES.items():
        candidates = [column for column in df.columns if column in aliases]
        if len(candidates) > 1:
            errors.append(f"Ambiguous columns for {name}: {', '.join(candidates)}")
    if "acquisition_date" in mapping and any(k in mapping for k in ("acquisition_year", "acquisition_month", "acquisition_day")):
        errors.append("Use acquisition_date OR separate year/month/day columns, not both")
    rows, parse_errors = parse_metadata(df, mapping, require_data_access=True)
    errors += [f"Row {row}: {message}" for row, message in parse_errors]
    for label, names in (("metadata filename", [r.filename.casefold() for r in rows]),
                         ("file name", [p.name.casefold() for p in files])):
        errors += [f"Duplicate {label}: {name}" for name, n in Counter(names).items() if n > 1]
    matched, unlisted, missing_files = match_files_to_metadata(files, rows)
    errors += [f"Missing metadata for file: {name}" for name in unlisted]
    errors += [f"Metadata row references a file outside the selected inputs: {name}" for name in missing_files]
    results = validate_all(matched, extract_dates=False)
    errors += [f"{r.filename}: {e}" for r in results for e in r.errors]
    if not results:
        errors.append("No files matched to metadata")
    entries = []
    for result in results:
        item = result.model_dump(mode="json")
        item["path"] = str(result.metadata.file_path)
        item["upload_type"] = result.metadata.upload_type.value
        item["size_bytes"] = result.metadata.file_path.stat().st_size
        entries.append(item)
    if not errors:
        seen = {}
        for item in entries:
            digest = file_digest(item["path"])
            item["sha256"] = digest
            if digest in seen:
                other = seen[digest]
                if {k: v for k, v in item["metadata"].items() if k != "filename"} != {k: v for k, v in other["metadata"].items() if k != "filename"}:
                    errors.append(f"{item['filename']}: identical content to {other['filename']} has conflicting metadata")
                else:
                    item["duplicate_of"] = other["filename"]
                    item["warnings"].append(f"Identical content to {other['filename']}; only one copy will be uploaded")
            else:
                seen[digest] = item
    return {"schema_version": 1, "operation": "validate", "success": not errors,
            "errors": errors, "files": entries}


def authenticate(api_url: str, email=None):
    url, key = supabase_config(api_url)
    bearer = os.getenv("DEADTREES_ACCESS_TOKEN")
    if bearer:
        return bearer
    email = email or os.getenv("DEADTREES_EMAIL")
    password = os.getenv("DEADTREES_PASSWORD")
    if email or password:
        if not (email and password):
            raise BatchError("Set both DEADTREES_EMAIL and DEADTREES_PASSWORD, or provide DEADTREES_ACCESS_TOKEN", 3)
        return create_auth_session(email, password, url, key)
    session = get_cached_session(api_url, refresh_if_expired=False)
    if session:
        if session.supabase_url.rstrip("/") != url.rstrip("/") or session.supabase_key != key:
            raise BatchError("Cached authentication target differs from selected Supabase", 3)
        session.get_valid_token()
        return session
    raise BatchError("Credentials missing: have the human run deadtrees-upload login in their terminal, or use an authorized credential provider for DEADTREES_ACCESS_TOKEN or DEADTREES_EMAIL and DEADTREES_PASSWORD", 3)


def file_digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def authenticated_user(api_url, token):
    url, key = supabase_config(api_url)
    bearer = token if isinstance(token, str) else token.get_valid_token()
    with httpx.Client(timeout=30) as client:
        response = client.get(url + "/auth/v1/user", headers={"apikey": key, "Authorization": f"Bearer {bearer}"})
    if response.status_code != 200:
        raise BatchError("Cannot verify upload account; check authentication", 3)
    user_id = response.json().get("id")
    if not isinstance(user_id, str) or not user_id:
        raise BatchError("Authentication response lacks user identity", 3)
    return user_id


def submit(report, data_path, metadata_path, api_url, token, resume=False, process=False):
    """Persist intent before mutation. Unknown outcomes require reconciliation."""
    from .models import FileMetadata, UploadType
    directory = data_path if data_path.is_dir() else data_path.parent
    journal_path = directory / ".deadtrees-upload-agent.json"
    lock_path = directory / ".deadtrees-upload-agent.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise BatchError("Another upload may be running. Inspect .deadtrees-upload-agent.lock; remove only after confirming its owner stopped", 5)
    try:
        with os.fdopen(lock_fd, "w") as lock:
            lock.write(str(os.getpid()))
        entries = report["files"]
        fingerprints = {item["metadata"]["filename"]: {
            "sha256": file_digest(item["path"]), "metadata": item["metadata"]
        } for item in entries}
        if any(fingerprints[item["metadata"]["filename"]]["sha256"] != item["sha256"] for item in entries):
            raise BatchError("Input content changed after validation; validate again before uploading", 2)
        target = validate_url(api_url)
        user_id = authenticated_user(target, token)
        if journal_path.exists():
            if not resume:
                raise BatchError("Upload receipt exists. Use --resume to inspect and skip confirmed uploads; do not delete it to retry unknown outcomes", 5)
            try:
                journal = json.loads(journal_path.read_text())
                if not isinstance(journal, dict) or not isinstance(journal.get("results"), dict):
                    raise ValueError("invalid structure")
            except (ValueError, OSError):
                raise BatchError("Cannot read upload receipt; preserve it and reconcile earlier uploads", 5)
            if journal.get("schema_version") != 1 or journal.get("api_url") != target or journal.get("inputs") != fingerprints or journal.get("user_id") != user_id:
                raise BatchError("Receipt target, account or inputs changed. Reconcile the earlier upload before starting a new batch", 5)
        else:
            if resume:
                raise BatchError("No agent upload receipt to resume", 5)
            if (directory / ".deadtrees-upload-session.json").exists():
                raise BatchError("Legacy wizard session exists; reconcile it before starting an agent upload", 5)
            journal = {"schema_version": 1, "api_url": target, "inputs": fingerprints, "user_id": user_id, "results": {}}
        for name, previous in journal["results"].items():
            if (name not in fingerprints or not isinstance(previous, dict)
                    or previous.get("state") not in {"in_flight", "unknown", "failed", "not_uploaded", "uploaded", "duplicate"}):
                raise BatchError("Invalid upload receipt state; preserve it for reconciliation", 5)
            if previous["state"] in {"uploaded", "duplicate"} and (type(previous.get("dataset_id")) is not int or previous["dataset_id"] <= 0):
                raise BatchError("Receipt lacks a confirmed dataset ID; reconcile before continuing", 5)
            if previous.get("state") in {"in_flight", "unknown", "failed"}:
                raise BatchError(f"{name}: upload outcome requires reconciliation (upload_id={previous.get('upload_id')}). Do not automatically re-upload", 5)
            if previous.get("processing") in {"in_flight", "unknown"}:
                raise BatchError(f"Dataset {previous.get('dataset_id')}: processing request unresolved; use status, do not requeue automatically", 5)
        atomic_json(journal_path, journal)
        for item in entries:
            name = item["metadata"]["filename"]
            previous = journal["results"].get(name, {})
            if file_digest(item["path"]) != fingerprints[name]["sha256"]:
                raise BatchError(f"{name}: file changed after validation; no further uploads attempted", 2)
            if previous.get("state") == "not_uploaded":
                previous = {}  # Explicit --resume may retry a known pre-write failure.
            metadata = FileMetadata(**item["metadata"], file_path=Path(item["path"]), upload_type=UploadType(item["upload_type"]))
            if not previous:
                # Full content identity catches duplicates even when filenames differ.
                duplicate = next((n for n, result in journal["results"].items()
                                  if result.get("state") == "uploaded" and fingerprints[n]["sha256"] == fingerprints[name]["sha256"]), None)
                if duplicate:
                    current_meta = {k: v for k, v in fingerprints[name]["metadata"].items() if k != "filename"}
                    prior_meta = {k: v for k, v in fingerprints[duplicate]["metadata"].items() if k != "filename"}
                    if current_meta != prior_meta:
                        raise BatchError(f"{name} duplicates {duplicate} with different metadata; clarify which metadata should apply", 5)
                    journal["results"][name] = {"state": "duplicate", "duplicate_of": duplicate,
                                               "dataset_id": journal["results"][duplicate]["dataset_id"]}
                    atomic_json(journal_path, journal)
                    continue
                upload_id = str(uuid.uuid4())
                previous = {"state": "in_flight", "upload_id": upload_id}
                journal["results"][name] = previous
                atomic_json(journal_path, journal)
                result = upload_file(metadata, token, target, upload_id=upload_id, expected_sha256=fingerprints[name]["sha256"])
                previous.update(state="uploaded" if result.success else "unknown" if result.outcome_unknown else "not_uploaded",
                                dataset_id=result.dataset_id, error=result.error)
                atomic_json(journal_path, journal)
                if not result.success:
                    return {"schema_version": 1, "operation": "upload", "success": False,
                            "receipt": str(journal_path), "results": journal["results"], "exit_code": 5 if result.outcome_unknown else 4}
            if process and previous.get("state") == "uploaded" and previous.get("processing") != "requested":
                previous["processing"] = "in_flight"
                previous["task_types"] = get_processing_tasks(metadata.upload_type)
                atomic_json(journal_path, journal)
                ok = trigger_processing(previous["dataset_id"], metadata.upload_type, token, target)
                previous["processing"] = "requested" if ok else "unknown"
                atomic_json(journal_path, journal)
                if not ok:
                    return {"schema_version": 1, "operation": "upload", "success": False,
                            "receipt": str(journal_path), "results": journal["results"], "exit_code": 5}
        return {"schema_version": 1, "operation": "upload", "success": True,
                "receipt": str(journal_path), "results": journal["results"], "exit_code": 0}
    finally:
        lock_path.unlink(missing_ok=True)


def status(dataset_id, api_url, email=None):
    token = authenticate(api_url, email)
    url, key = supabase_config(api_url)
    bearer = token if isinstance(token, str) else token.get_valid_token()
    with httpx.Client(timeout=30) as client:
        response = client.get(url + "/rest/v1/v2_statuses", params={"dataset_id": f"eq.{dataset_id}", "select": "*"},
                              headers={"apikey": key, "Authorization": f"Bearer {bearer}"})
    if response.status_code != 200:
        raise BatchError(f"Status lookup failed (HTTP {response.status_code}); no processing conclusion available", 4)
    rows = response.json()
    if not rows:
        raise BatchError("Dataset status absent or inaccessible; this does not establish completion", 4)
    return {"schema_version": 1, "operation": "status", "success": True, "dataset_id": dataset_id, "status": rows[0]}
