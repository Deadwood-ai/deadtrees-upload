"""Behavioral regression checks with synthetic files and mocked HTTP only."""
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import httpx
import numpy as np
import pytest
import rasterio
from PIL import Image
from typer.testing import CliRunner

from deadtrees_upload import batch
from deadtrees_upload.cli import app
from deadtrees_upload.models import FileMetadata, UploadType
from deadtrees_upload.upload import upload_file


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for key in list(os.environ):
        if key.startswith("DEADTREES_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("DEADTREES_UPLOAD_CACHE_DIR", str(tmp_path / "cache"))
    # No test can accidentally send HTTP to production or shared local services.
    def blocked(*args, **kwargs):
        raise AssertionError("Unexpected real network request")
    monkeypatch.setattr(httpx.Client, "send", blocked)
    monkeypatch.setattr(batch, "authenticated_user", lambda *args: "synthetic-user")


@pytest.fixture
def inputs(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    path = data / "rgb.tif"
    with rasterio.open(path, "w", driver="GTiff", width=32, height=32, count=3,
                       dtype="uint8", crs="EPSG:32632", transform=rasterio.transform.from_origin(400000, 5300000, .1, .1)) as dst:
        dst.write(np.ones((3, 32, 32), dtype=np.uint8))
    metadata = tmp_path / "metadata.csv"
    metadata.write_text("filename,license,platform,authors,acquisition_year,data_access\nrgb.tif,CC BY,drone,Example Author,2024,private\n")
    return data, metadata


def invoke(inputs, *args):
    data, metadata = inputs
    return CliRunner().invoke(app, ["--data-dir", str(data), "--metadata", str(metadata), "--json", *args])


def test_offline_plan_no_auth_or_writes(inputs):
    data, _ = inputs
    result = invoke(inputs, "--dry-run")
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["success"] and report["files"][0]["metadata"]["data_access"] == "private"
    assert list(data.iterdir()) == [data / "rgb.tif"]


@pytest.mark.parametrize("args,code,message", [([], 2, "requires --yes"), (["--yes"], 3, "Credentials missing")])
def test_no_prompt_missing_authority_or_credentials(inputs, args, code, message):
    result = invoke(inputs, *args)
    assert result.exit_code == code, result.output
    assert message in json.loads(result.stdout)["errors"][0]


def test_missing_inputs_closed_stdin():
    result = CliRunner().invoke(app, ["--json"])
    assert result.exit_code == 2
    assert "--metadata" in json.loads(result.stdout)["errors"][0]


@pytest.mark.parametrize("change", ["missing_year", "duplicate_row", "unmatched", "invalid_date", "ambiguous"])
def test_metadata_fails_entire_plan(inputs, change):
    data, metadata = inputs
    text = metadata.read_text()
    if change == "missing_year": text = text.replace(",2024,", ",,")
    if change == "duplicate_row": text += text.splitlines()[1] + "\n"
    if change == "unmatched": text = text.replace("rgb.tif", "absent.tif")
    if change == "invalid_date": text = text.replace("acquisition_year", "acquisition_date").replace("2024", "2024-02-31")
    if change == "ambiguous": text = text.replace("license,", "license,licence,").replace("CC BY,", "CC BY,MIT,")
    metadata.write_text(text)
    result = invoke(inputs, "--dry-run")
    assert result.exit_code == 2, result.output
    assert not json.loads(result.stdout)["success"]


def test_synthetic_zip_valid_and_invalid(tmp_path):
    from deadtrees_upload.validate_zip import validate_zip
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "green").save(buffer, format="JPEG")
    path = tmp_path / "images.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for n in range(3): archive.writestr(f"images/{n}.jpg", buffer.getvalue())
    result = validate_zip(path)
    assert not result.is_valid and any("100 KiB" in w for w in result.errors)
    buffer = io.BytesIO()
    pixels = np.random.default_rng(42).integers(0, 256, (512, 512, 3), dtype=np.uint8)
    Image.fromarray(pixels).save(buffer, format="JPEG", quality=95)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for n in range(3): archive.writestr(f"images/{n}.jpg", buffer.getvalue())
    assert validate_zip(path).is_valid
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_LZMA) as archive:
        archive.writestr("image.jpg", buffer.getvalue())
    assert not validate_zip(path).is_valid
    with zipfile.ZipFile(path, "w") as archive:
        for n in range(3): archive.writestr(f"{n}.jpg", b"not a jpeg")
    assert not validate_zip(path).is_valid
    with zipfile.ZipFile(path, "w") as archive:
        for n in range(3): archive.writestr(f"DJI_MS_{n}.tif", b"multispectral")
    assert not validate_zip(path).is_valid


def test_multispectral_geotiff_rejected(tmp_path):
    from deadtrees_upload.validate_geotiff import validate_geotiff
    path = tmp_path / "ms.tif"
    with rasterio.open(path, "w", driver="GTiff", width=8, height=8, count=5,
                       dtype="uint16", crs="EPSG:32632", transform=rasterio.transform.from_origin(400000, 5300000, 1, 1)) as dst:
        dst.write(np.ones((5, 8, 8), dtype=np.uint16))
    assert not validate_geotiff(path)[0].is_valid


def http_mock(monkeypatch, handler):
    real_client = httpx.Client
    class MockClient(real_client):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, transport=httpx.MockTransport(handler))
        def send(self, *args, **kwargs):
            # autouse network guard replaces parent send; use captured implementation.
            return REAL_SEND(self, *args, **kwargs)
    monkeypatch.setattr(httpx, "Client", MockClient)


REAL_SEND = httpx.Client.send


def metadata_for(inputs):
    return FileMetadata(filename="rgb.tif", license="CC BY", platform="drone", authors=["Example"],
                        acquisition_year=2024, file_path=inputs[0] / "rgb.tif", upload_type=UploadType.geotiff)


def test_chunk_api_payload_and_success(inputs, monkeypatch):
    requests = []
    def handle(request):
        requests.append(request)
        assert request.url.path == "/api/v1/datasets/chunk"
        body = request.read()
        assert b'name="aquisition_year"' in body and b'name="authors"' in body
        return httpx.Response(200, json={"id": 123})
    http_mock(monkeypatch, handle)
    result = upload_file(metadata_for(inputs), "test-token", "https://example.test/api/v1/", chunk_size=2000)
    assert result.success and result.dataset_id == 123
    assert len(requests) > 1


@pytest.mark.parametrize("failure", ["timeout", "http500", "bad_final"])
def test_ambiguous_upload_never_replayed(inputs, monkeypatch, failure):
    calls = []
    def handle(request):
        calls.append(request)
        if failure == "timeout": raise httpx.ReadTimeout("secret-token must not leak")
        return httpx.Response(500 if failure == "http500" else 200, json={"detail": "secret-token"})
    http_mock(monkeypatch, handle)
    result = upload_file(metadata_for(inputs), "secret-token", "https://example.test/api/v1")
    assert not result.success and result.outcome_unknown
    assert len(calls) == 1 and "secret-token" not in result.model_dump_json()


def test_receipt_resume_and_changed_input(inputs, monkeypatch):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"id": 123})
    http_mock(monkeypatch, handle)
    report = batch.plan(*inputs)
    result = batch.submit(report, *inputs, "https://example.test/api/v1", "test-token")
    assert result["success"] and len(calls) == 1
    result = batch.submit(report, *inputs, "https://example.test/api/v1", "test-token", resume=True)
    assert result["success"] and len(calls) == 1
    with (inputs[0] / "rgb.tif").open("ab") as stream: stream.write(b"changed")
    with pytest.raises(batch.BatchError, match="changed after validation"):
        batch.submit(report, *inputs, "https://example.test/api/v1", "test-token", resume=True)


def test_unknown_receipt_blocks_resume(inputs, monkeypatch):
    calls = []
    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout("lost response")
    http_mock(monkeypatch, handle)
    report = batch.plan(*inputs)
    result = batch.submit(report, *inputs, "https://example.test/api/v1", "test-token")
    assert result["exit_code"] == 5
    with pytest.raises(batch.BatchError, match="requires reconciliation"):
        batch.submit(report, *inputs, "https://example.test/api/v1", "test-token", resume=True)
    assert len(calls) == 1


def test_processing_failure_keeps_dataset_and_prevents_requeue(inputs, monkeypatch):
    calls = []
    def handle(request):
        calls.append(request)
        if request.method == "PUT":
            tasks = json.loads(request.content)["task_types"]
            assert "deadwood_v1" in tasks and "deadwood" not in tasks
            return httpx.Response(503)
        return httpx.Response(200, json={"id": 123})
    http_mock(monkeypatch, handle)
    report = batch.plan(*inputs)
    result = batch.submit(report, *inputs, "https://example.test/api/v1", "test-token", process=True)
    assert result["results"]["rgb.tif"]["dataset_id"] == 123 and result["exit_code"] == 5
    with pytest.raises(batch.BatchError, match="processing request unresolved"):
        batch.submit(report, *inputs, "https://example.test/api/v1", "test-token", resume=True, process=True)
    assert len(calls) == 2


def test_custom_target_no_production_auth_fallback(monkeypatch):
    from deadtrees_upload.config import supabase_config
    with pytest.raises(ValueError, match="Custom API"):
        supabase_config("https://localhost.attacker.test/api/v1")


def test_status_reads_actual_flags(monkeypatch):
    monkeypatch.setenv("DEADTREES_ACCESS_TOKEN", "test-token")
    def handle(request):
        assert request.method == "GET" and request.url.path == "/rest/v1/v2_statuses"
        assert request.url.params["dataset_id"] == "eq.123"
        return httpx.Response(200, json=[{"dataset_id": 123, "is_upload_done": True, "is_cog_done": False}])
    http_mock(monkeypatch, handle)
    result = CliRunner().invoke(app, ["status", "123", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"]["is_cog_done"] is False


def test_full_unattended_auth_upload_flow(inputs, monkeypatch):
    monkeypatch.setenv("DEADTREES_EMAIL", "synthetic@example.test")
    monkeypatch.setenv("DEADTREES_PASSWORD", "synthetic-password")
    # Restore real identity function for this integration path.
    import importlib
    real_identity = importlib.reload(batch).authenticated_user
    monkeypatch.setattr(batch, "authenticated_user", real_identity)
    calls = []
    def handle(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/auth/v1/token":
            assert json.loads(request.content)["password"] == "synthetic-password"
            return httpx.Response(200, json={"access_token": "synthetic-token", "refresh_token": "synthetic-refresh",
                                           "user": {"id": "synthetic-user"}, "expires_in": 3600})
        if request.url.path == "/auth/v1/user": return httpx.Response(200, json={"id": "synthetic-user"})
        return httpx.Response(200, json={"id": 42})
    http_mock(monkeypatch, handle)
    result = invoke(inputs, "--yes")
    assert result.exit_code == 0, result.output
    assert calls == [("POST", "/auth/v1/token"), ("GET", "/auth/v1/user"), ("POST", "/api/v1/datasets/chunk")]
    receipt = (inputs[0] / ".deadtrees-upload-agent.json").read_text()
    assert all(secret not in result.stdout + receipt for secret in ["synthetic-password", "synthetic-token", "synthetic-refresh"])


def test_401_refresh_is_bounded(inputs, monkeypatch):
    from deadtrees_upload.auth import AuthSession
    import time
    session = AuthSession("old", "refresh", "user", time.time() + 3600, "https://auth.example.test", "anon")
    calls = []
    def handle(request):
        calls.append(request.url.path)
        if request.url.path == "/auth/v1/token":
            return httpx.Response(200, json={"access_token": "new", "refresh_token": "next", "expires_in": 3600})
        if request.headers["Authorization"] == "Bearer old": return httpx.Response(401)
        return httpx.Response(200, json={"id": 12})
    http_mock(monkeypatch, handle)
    result = upload_file(metadata_for(inputs), session, "https://example.test/api/v1")
    assert result.success and calls == ["/api/v1/datasets/chunk", "/auth/v1/token", "/api/v1/datasets/chunk"]
    http_mock(monkeypatch, lambda request: httpx.Response(401))
    result = upload_file(metadata_for(inputs), session, "https://example.test/api/v1", max_retries=1)
    assert not result.success


def test_cached_refresh_persists_private_tokens(tmp_path, monkeypatch):
    from deadtrees_upload.auth import AuthSession, save_auth_session, load_auth_session, get_auth_session_path
    session = AuthSession("old", "refresh", "user", 0, "https://auth.example.test", "anon")
    target = "https://example.test/api/v1"
    save_auth_session(session, target)
    cached = load_auth_session(target)
    http_mock(monkeypatch, lambda request: httpx.Response(200, json={"access_token": "rotated", "refresh_token": "new-refresh", "expires_in": 3600}))
    cached.get_valid_token()
    assert load_auth_session(target).refresh_token == "new-refresh"
    assert get_auth_session_path(target).stat().st_mode & 0o777 == 0o600
    assert "new-refresh" not in repr(cached)


def test_receipt_account_binding_and_lock(inputs, monkeypatch):
    report = batch.plan(*inputs)
    http_mock(monkeypatch, lambda request: httpx.Response(200, json={"id": 1}))
    batch.submit(report, *inputs, "https://example.test/api/v1", "token")
    monkeypatch.setattr(batch, "authenticated_user", lambda *args: "another-user")
    with pytest.raises(batch.BatchError, match="account"):
        batch.submit(report, *inputs, "https://example.test/api/v1", "token", resume=True)
    (inputs[0] / ".deadtrees-upload-agent.lock").write_text("owner")
    with pytest.raises(batch.BatchError, match="Another upload"):
        batch.submit(report, *inputs, "https://example.test/api/v1", "token", resume=True)


def test_duplicate_plan_metadata_conflict(inputs):
    data, metadata = inputs
    (data / "copy.tif").write_bytes((data / "rgb.tif").read_bytes())
    text = metadata.read_text()
    metadata.write_text(text + text.splitlines()[1].replace("rgb.tif", "copy.tif") + "\n")
    report = batch.plan(*inputs)
    assert report["success"] and any(item.get("duplicate_of") for item in report["files"])
    metadata.write_text(metadata.read_text().replace("copy.tif,CC BY", "copy.tif,MIT"))
    assert not batch.plan(*inputs)["success"]


def test_source_closed_stdin_plan(inputs, monkeypatch):
    import subprocess
    command = [sys.executable, "-m", "deadtrees_upload.cli", "--data-dir", str(inputs[0]),
               "--metadata", str(inputs[1]), "--dry-run", "--json"]
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["success"]


def test_duplicate_column_headers_rejected(inputs):
    _, metadata = inputs
    text = metadata.read_text().replace("license,", "license,license,").replace("CC BY,", "CC BY,MIT,")
    metadata.write_text(text)
    result = invoke(inputs, "--dry-run")
    assert result.exit_code == 2 and "Duplicate column names" in result.stdout


def test_corrupt_receipt_preserved(inputs, monkeypatch):
    path = inputs[0] / ".deadtrees-upload-agent.json"
    path.write_text("corrupt receipt")
    with pytest.raises(batch.BatchError, match="Cannot read upload receipt"):
        batch.submit(batch.plan(*inputs), *inputs, "https://example.test/api/v1", "token", resume=True)
    assert path.read_text() == "corrupt receipt"


def test_receipt_save_failure_prevents_upload(inputs, monkeypatch):
    def fail(*args): raise OSError("disk full")
    monkeypatch.setattr(batch, "atomic_json", fail)
    # The autouse network guard would fail if any upload was attempted.
    with pytest.raises(OSError, match="disk full"):
        batch.submit(batch.plan(*inputs), *inputs, "https://example.test/api/v1", "token")
    assert not (inputs[0] / ".deadtrees-upload-agent.lock").exists()


def test_human_wizard_route_preserved(inputs, monkeypatch):
    from types import SimpleNamespace
    from deadtrees_upload import cli
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    calls = []
    monkeypatch.setattr(cli, "authenticate", lambda url: "synthetic-token")
    monkeypatch.setattr(cli, "check_existing_session", lambda path: None)
    monkeypatch.setattr(cli, "map_columns", lambda df, path, mapping, missing: mapping)
    monkeypatch.setattr(cli, "do_upload", lambda *args, **kwargs: calls.append(args) or [])
    cli.main(SimpleNamespace(invoked_subcommand=None), data_dir=inputs[0], metadata=inputs[1],
             email=None, api_url=cli.DEFAULT_API_URL, non_interactive=False, json_output=False,
             yes=False, resume=False, process=False, dry_run=False)
    assert len(calls) == 1 and calls[0][0][0].is_valid


@pytest.mark.parametrize("access", [None, "", "   "])
@pytest.mark.parametrize("upload", [False, True])
def test_unattended_access_must_be_explicit_before_auth(inputs, access, upload):
    _, metadata = inputs
    text = metadata.read_text()
    text = text.replace(",data_access", "").replace(",private", "") if access is None else text.replace(",private", "," + access)
    metadata.write_text(text)
    result = invoke(inputs, *( ["--yes"] if upload else ["--dry-run"] ))
    assert result.exit_code == 2, result.output
    report = json.loads(result.stdout)
    assert any("Explicit data_access" in e for e in report["errors"])
    assert not any(f.get("metadata", {}).get("data_access") == "public" for f in report["files"])
    assert not (inputs[0] / ".deadtrees-upload-agent.json").exists()


@pytest.mark.parametrize("access", ["public", "private", "viewonly"])
def test_explicit_access_values_and_alias(inputs, access):
    _, metadata = inputs
    metadata.write_text(metadata.read_text().replace("data_access", "visibility").replace("private", access))
    result = invoke(inputs, "--dry-run")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["files"][0]["metadata"]["data_access"] == access


def test_legacy_parser_keeps_public_default(inputs):
    from deadtrees_upload.metadata import read_metadata_file, find_column_mapping, parse_metadata
    _, metadata = inputs
    metadata.write_text(metadata.read_text().replace(",data_access", "").replace(",private", ""))
    df = read_metadata_file(metadata)
    rows, errors = parse_metadata(df, find_column_mapping(df)[0])
    assert not errors and rows[0].data_access.value == "public"


def test_login_refuses_closed_stdin_without_network():
    result = CliRunner().invoke(app, ["login"])
    assert result.exit_code == 3 and "human terminal" in result.output


def test_human_login_saves_then_agent_reuses_session(monkeypatch, capsys):
    from deadtrees_upload import cli
    from deadtrees_upload.auth import get_auth_session_path
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    prompts, requests = [], []
    def ask(label, **kwargs):
        prompts.append((label, kwargs))
        return "synthetic-human@example.test" if label == "Email" else "synthetic-secret"
    monkeypatch.setattr(cli.Prompt, "ask", ask)
    def handle(request):
        requests.append((request.method, request.url.path))
        assert request.url.path == "/auth/v1/token"
        return httpx.Response(200, json={"access_token": "saved-test-token", "refresh_token": "saved-test-refresh",
                                        "user": {"id": "test-human"}, "expires_in": 3600})
    http_mock(monkeypatch, handle)
    cli.login(cli.DEFAULT_API_URL)
    assert prompts == [("Email", {}), ("Password", {"password": True})]
    assert requests == [("POST", "/auth/v1/token")]
    assert get_auth_session_path(cli.DEFAULT_API_URL).stat().st_mode & 0o777 == 0o600
    session = batch.authenticate(cli.DEFAULT_API_URL)
    assert session.user_id == "test-human" and len(requests) == 1
    output = capsys.readouterr()
    assert "Session saved" in output.out
    assert all(secret not in output.out + output.err for secret in ["synthetic-secret", "saved-test-token", "saved-test-refresh"])


def test_login_persistence_failure_is_not_success(monkeypatch, capsys):
    from deadtrees_upload import cli
    from deadtrees_upload.auth import AuthSession
    import typer
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.Prompt, "ask", lambda *args, **kwargs: "fake")
    monkeypatch.setattr(cli, "create_auth_session", lambda *args: AuthSession("token", "refresh", "id", 0, "url", "key"))
    def fail(*args): raise OSError("disk unavailable")
    monkeypatch.setattr(cli, "save_auth_session", fail)
    with pytest.raises(typer.Exit) as error:
        cli.login(cli.DEFAULT_API_URL)
    assert error.value.exit_code == 3
    captured = capsys.readouterr()
    assert "Session saved" not in captured.out


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
def test_draft_helper_from_unrelated_directory_preserves_unknowns(inputs, tmp_path, suffix):
    import subprocess
    import pandas as pd
    helper = Path(__file__).parents[1] / ".agents/skills/deadtrees-upload/scripts/prepare_metadata.py"
    target = tmp_path / ("new-draft" + suffix)
    with rasterio.open(inputs[0] / "rgb.tif", "r+") as dataset:
        dataset.update_tags(TIFFTAG_DATETIME="2022:05:19 10:00:00")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (inputs[0] / "readme.txt").write_text("contributor note")
    original = (inputs[0] / "rgb.tif").read_bytes()
    result = subprocess.run([sys.executable, str(helper), "--data-dir", str(inputs[0]), "--output", str(target)],
                            cwd=unrelated, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    inventory = json.loads(result.stdout)
    assert inventory["files"][0]["embedded_date_candidate"] == [2022, 5, 19]
    assert inventory["unselected_entries"] == ["readme.txt"]
    frame = pd.read_csv(target) if suffix == ".csv" else pd.read_excel(target)
    for field in ["authors", "license", "platform", "data_access", "acquisition_year", "acquisition_month", "acquisition_day"]:
        assert pd.isna(frame.iloc[0][field])
    assert not batch.plan(inputs[0], target)["success"]
    again = subprocess.run([sys.executable, str(helper), "--data-dir", str(inputs[0]), "--output", str(target)],
                           cwd=unrelated, capture_output=True, text=True, timeout=20)
    assert again.returncode == 2 and "already exists" in again.stdout
    assert (inputs[0] / "rgb.tif").read_bytes() == original


def test_xlsx_draft_preserves_formula_like_filename(inputs, tmp_path):
    import importlib.util
    import pandas as pd
    helper = Path(__file__).parents[1] / ".agents/skills/deadtrees-upload/scripts/prepare_metadata.py"
    spec = importlib.util.spec_from_file_location("draft_helper", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = inputs[0] / "rgb.tif"
    source.rename(inputs[0] / "=SUM(1).tif")
    output = tmp_path / "literal.xlsx"
    module.prepare(inputs[0], output)
    assert pd.read_excel(output).iloc[0]["filename"] == "=SUM(1).tif"


@pytest.mark.parametrize("partial", [False, True])
def test_auth_rejection_tracks_prior_accepted_chunks(inputs, monkeypatch, partial):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200 if partial and len(calls) == 1 else 401, json={})
    http_mock(monkeypatch, handle)
    result = upload_file(metadata_for(inputs), "token", "https://example.test/api/v1", chunk_size=2000)
    assert not result.success and result.outcome_unknown is partial
    assert len(calls) == (2 if partial else 1)


def test_explicit_resume_retries_only_known_prewrite_failure(inputs, monkeypatch):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(401 if len(calls) == 1 else 200, json={"id": 321})
    http_mock(monkeypatch, handle)
    report = batch.plan(*inputs)
    first = batch.submit(report, *inputs, "https://example.test/api/v1", "token")
    assert first["results"]["rgb.tif"]["state"] == "not_uploaded"
    assert batch.submit(report, *inputs, "https://example.test/api/v1", "token", resume=True)["success"]
    assert len(calls) == 2


def test_refresh_survives_cache_write_failure(monkeypatch, capsys):
    from deadtrees_upload import auth
    session = auth.AuthSession("old", "refresh", "user", 0, "https://auth.example.test", "anon", "https://example.test/api/v1")
    def fail(*args): raise OSError("sensitive disk detail")
    monkeypatch.setattr(auth, "save_auth_session", fail)
    http_mock(monkeypatch, lambda request: httpx.Response(200, json={"access_token": "rotated", "refresh_token": "new-refresh", "expires_in": 3600}))
    assert session.get_valid_token() == "rotated"
    output = capsys.readouterr()
    assert "cache could not be saved" in output.err
    assert all(secret not in output.err for secret in ["rotated", "new-refresh", "sensitive"])


def test_cache_url_slash_and_legacy_lookup(monkeypatch):
    from deadtrees_upload import auth
    target = "https://example.test/api/v1"
    session = auth.AuthSession("token", "refresh", "user", 9999999999, "https://auth.example.test", "anon")
    auth.save_auth_session(session, target + "/")
    canonical = auth.get_auth_session_path(target)
    assert canonical == auth.get_auth_session_path(target + "/")
    legacy = canonical.with_name(canonical.stem + "_.json")
    canonical.rename(legacy)
    assert auth.load_auth_session(target).access_token == "token"
    auth.clear_auth_session(target)
    assert auth.load_auth_session(target) is None


@pytest.mark.parametrize("suffix", ["csv", "xlsx"])
def test_blank_padded_metadata_headers_are_ignored(inputs, suffix):
    import pandas as pd
    data, metadata = inputs
    rows = [line.split(",") + ["", ""] for line in metadata.read_text().splitlines()]
    destination = metadata.with_suffix("." + suffix)
    if suffix == "csv": destination.write_text("\n".join(",".join(row) for row in rows))
    else: pd.DataFrame(rows).to_excel(destination, index=False, header=False)
    assert batch.plan(data, destination)["success"]


def test_later_batch_file_mutation_stops_before_send(inputs, monkeypatch):
    data, metadata = inputs
    later = data / "second.tif"
    later.write_bytes((data / "rgb.tif").read_bytes())
    metadata.write_text(metadata.read_text() + "second.tif,CC BY,drone,Example Author,2024,private\n")
    report = batch.plan(*inputs)
    calls = []
    def handle(request):
        calls.append(request)
        later.write_bytes(b"changed")
        return httpx.Response(200, json={"id": 1})
    http_mock(monkeypatch, handle)
    with pytest.raises(batch.BatchError, match="changed after validation"):
        batch.submit(report, *inputs, "https://example.test/api/v1", "token")
    assert len(calls) == 1
    assert json.loads((data / ".deadtrees-upload-agent.json").read_text())["results"]["rgb.tif"]["dataset_id"] == 1


@pytest.mark.parametrize("partial", [False, True])
def test_changed_transmitted_content_never_finalizes(inputs, monkeypatch, partial):
    path = inputs[0] / "rgb.tif"
    # Exceed buffered-reader prefetch so the in-place mutation affects unread bytes.
    path.write_bytes(b"a" * 40000)
    digest = batch.file_digest(path)
    calls = []
    def handle(request):
        calls.append(request)
        with path.open("r+b") as stream:
            stream.seek(35000)
            stream.write(b"changed")
        return httpx.Response(200, json={"id": 1})
    http_mock(monkeypatch, handle)
    if not partial: path.write_bytes(b"b" * 40000)
    result = upload_file(metadata_for(inputs), "token", "https://example.test/api/v1", chunk_size=20000 if partial else 50000, expected_sha256=digest)
    assert not result.success and result.outcome_unknown is partial
    assert len(calls) == (1 if partial else 0)


@pytest.mark.parametrize("marker", [".deadtrees-upload-agent.json", ".deadtrees-upload-agent.lock"])
def test_wizard_cannot_bypass_agent_receipts(inputs, monkeypatch, marker):
    from types import SimpleNamespace
    from deadtrees_upload import cli
    import typer
    (inputs[0] / marker).write_text("preserve")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli, "authenticate", lambda url: "token")
    with pytest.raises(typer.Exit) as error:
        cli.main(SimpleNamespace(invoked_subcommand=None), data_dir=inputs[0], metadata=inputs[1],
                 email=None, api_url=cli.DEFAULT_API_URL, non_interactive=False, json_output=False,
                 yes=False, resume=False, process=False, dry_run=False)
    assert error.value.exit_code == 5
    assert (inputs[0] / marker).read_text() == "preserve"



def test_later_contribution_in_new_directory_preserves_first_batch(inputs, monkeypatch):
    data, metadata = inputs
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"id": len(calls)})
    http_mock(monkeypatch, handle)
    batch.submit(batch.plan(*inputs), *inputs, "https://example.test/api/v1", "token")
    receipt = data / ".deadtrees-upload-agent.json"
    original = receipt.read_bytes()
    later = data.parent / "later"
    later.mkdir()
    with rasterio.open(later / "rgb.tif", "w", driver="GTiff", width=32, height=32, count=3,
                       dtype="uint8", crs="EPSG:32632", transform=rasterio.transform.from_origin(400000, 5300000, .1, .1)) as dst:
        dst.write(np.full((3, 32, 32), 7, dtype=np.uint8))
    result = batch.submit(batch.plan(later, metadata), later, metadata, "https://example.test/api/v1", "token")
    assert result["success"] and len(calls) == 2
    assert receipt.read_bytes() == original
