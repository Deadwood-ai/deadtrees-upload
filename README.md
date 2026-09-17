# DeadTrees Upload CLI

Contribute aerial forest imagery to [deadtrees.earth](https://deadtrees.earth),
which builds orthomosaics, map products and deadwood/tree-cover predictions.
Upload existing RGB GeoTIFFs or ZIPs of raw RGB drone photos. Raw photos do **not**
need to be processed first: the platform can run OpenDroneMap (ODM).

## Start from the repository URL

Point an agent to [Deadwood-ai/deadtrees-upload](https://github.com/Deadwood-ai/deadtrees-upload)
and ask it to follow `.agents/skills/deadtrees-upload/SKILL.md` for your contributor
folder. Keep the checkout: it contains the CLI, skill, draft helper and this
metadata/API reference together. No separate skill install, package index or
release download is needed.

Use Python 3.10+ and Git. For example, in a chosen working directory:

```sh
git clone https://github.com/Deadwood-ai/deadtrees-upload.git
cd deadtrees-upload
# If a particular revision was agreed, check it out before installation.
git rev-parse HEAD
DT_UPLOAD_REPO="$PWD"
python3 -m venv "$DT_UPLOAD_REPO/.venv"
"$DT_UPLOAD_REPO/.venv/bin/python" -m pip install "$DT_UPLOAD_REPO"
"$DT_UPLOAD_REPO/.venv/bin/deadtrees-upload" --help
```

Use that checkout's skill and documentation with that installed CLI. Reinstall
from the checkout after changing revisions. Record `git rev-parse HEAD`; the
package version alone does not identify the source revision. Paths in the skill
are relative to the skill file, **not** the shell's working directory. When using
another agent outside the checkout, provide the absolute skill path explicitly.
The commands below work from any directory when `DT_UPLOAD_REPO` is the absolute
checkout path; it is a shell variable, not machine-specific agent configuration.
On Windows, use the corresponding `.venv\Scripts\python.exe` and
`.venv\Scripts\deadtrees-upload.exe` paths.

### Start with a contributor folder

```sh
"$DT_UPLOAD_REPO/.venv/bin/python" \
  "$DT_UPLOAD_REPO/.agents/skills/deadtrees-upload/scripts/prepare_metadata.py" \
  --data-dir /path/to/contribution --output /path/to/metadata-draft.csv
```

The helper inventories top-level GeoTIFF/ZIP candidates using the CLI's existing
validation and date extraction, lists unselected entries, and creates a new CSV
(or `.xlsx`) draft. It refuses to overwrite a file. Dates appear only as embedded
candidates in its JSON output: confirm their meaning before copying them into the
draft. Authorship, license, capture platform, date and visibility stay blank until
known. Filenames, timestamps and band counts alone do not establish those facts.
Invalid candidates remain visible for review; draft creation is not validation
success. For loose drone photos or subfolders, first agree which flight/area
belongs together. ZIP selected originals only with authorization, preserve their
EXIF, and do not mix unrelated flights or automatically convert imagery.

Complete the draft with the contributor's decisions, then run offline validation.
Missing/blank visibility fails unattended validation; explicitly choose `public`,
`private` or `viewonly`. Do not fill other unknowns merely to make validation pass.

## Automation

```sh
# Offline: no authentication, network, cache writes or receipt changes.
"$DT_UPLOAD_REPO/.venv/bin/deadtrees-upload" --data-dir ./data --metadata metadata.csv --dry-run --json

# After authorization for these files, metadata and target:
"$DT_UPLOAD_REPO/.venv/bin/deadtrees-upload" --data-dir ./data --metadata metadata.csv --non-interactive --yes --json

# Add --process if platform processing is also authorized.
"$DT_UPLOAD_REPO/.venv/bin/deadtrees-upload" --data-dir ./data --metadata metadata.csv --non-interactive --yes --process --json

# Inspect processing flags without submitting anything.
"$DT_UPLOAD_REPO/.venv/bin/deadtrees-upload" status 123 --json
```

`--data-dir` accepts one file or a directory of top-level `.tif`, `.tiff`,
`.geotiff` and `.zip` files. It does not recurse. `--dry-run`, `--json`, automation
flags and closed stdin select unattended behavior. Missing information fails
immediately; it never falls back to a password or metadata prompt. `--json`
emits one JSON object on stdout. CLI syntax errors use stderr. Without arguments
in a terminal, the original human wizard remains available, including template
creation, column mapping, stored login and automatic processing.

Automated batches validate **all** selected inputs before any network request.
A single-file selection needs metadata for only that selected file.
They reject malformed rows, ambiguous columns, duplicate filenames and unmatched
files. File warnings remain visible; assess them before submitting. Local
validation is not a guarantee that reconstruction or models will succeed.

### Metadata

CSV (UTF-8) and XLSX are supported. Use canonical columns for automation:

```csv
filename,license,platform,authors,acquisition_year,data_access
forest.tif,CC BY,drone,Example Author;Second Author,2024,private
```

| Field | Contract |
|---|---|
| `filename` | Required unique basename matching a selected file (case-insensitive). |
| `license` | Required: `CC BY`, `CC BY-SA`, `CC BY-NC-SA`, `CC BY-NC`, `MIT`. Established spelling aliases are accepted. |
| `platform` | Required: `drone` or `airborne`; UAV/aircraft aliases are accepted. |
| `authors` | Required, nonempty; separate names with semicolons. |
| `acquisition_year` | Required, 1980–2099. Optional `acquisition_month` and `acquisition_day` must form a valid date. |
| `acquisition_date` | Alternative to separate date columns. Prefer `YYYY`, `YYYY-MM`, `YYYY-MM-DD`; do not mix both representations. |
| `data_access` | **Required for unattended validation/upload:** `public`, `private`, `viewonly`. Missing/blank values fail. The human wizard retains its public default. |
| `additional_information`, `citation_doi` | Optional text. |

Automation does not infer missing month/day from embedded timestamps. It never
chooses authorship, licensing or access permission for the contributor.

### Input boundaries

- **GeoTIFF:** embedded geographic/projected CRS and transform, RGB bands in
  positions 1–3, optionally alpha in position 4. Sidecars are not uploaded.
  Non-RGB, more than four bands, or an unexplained fourth band fail this workflow.
  Non-8-bit imagery with established RGB color interpretations receives a processing-compatibility warning. Header and bounded
  pixel checks cannot establish every pixel's integrity or true sensor semantics.
- **Raw-drone ZIP:** Store or Deflate compression; unencrypted members; at least
  three image candidates surviving the worker size/name filters. JPEG, PNG, TIFF, BMP and WebP are checked with Pillow;
  RAW/DNG are accepted by the worker as candidates but decoding is unverified
  locally. Camera-specific CR2/NEF/ARW are not worker candidates.
- Current ODM code excludes images <=100 KiB and names containing `_MS_`.
  Mixed archives receive warnings identifying that behavior. Multispectral-only
  archives fail. Missing GPS, insufficient overlap or unknown sensor layouts need
  contributor clarification. No new preprocessing or multispectral support is
  provided by this CLI.

These checks intentionally distinguish supported RGB contributions from the
platform's broader extension acceptance. The platform stores GeoTIFF uploads
before technical processing; an upload response does not validate imagery.

### Authentication and endpoints

For a first-time human login, give the user this command to run in **their own
terminal on the same machine/OS account** as the agent:

```sh
"$DT_UPLOAD_REPO/.venv/bin/deadtrees-upload" login
```

The human enters email and a masked password locally. Do not ask for the password
in chat or run the interactive handoff through an agent transcript. `login` uses
the existing Supabase password/session route, saves a refreshable session with
private file permissions, and exits without upload or processing. It refuses
closed stdin. A save failure is an error; a successful login does not authorize
an upload. Subsequent agent commands reuse that cache for the same API target
without needing the password. Run `login` again to replace a stale session or
change account; existing upload receipts remain bound to their original account.

The cache follows `XDG_CACHE_HOME/deadtrees_upload` or
`~/.cache/deadtrees_upload`; `DEADTREES_UPLOAD_CACHE_DIR` can select another local
location. Keep the default for simple same-user onboarding. A different OS user,
remote host or container will not automatically share that session: log in in the
intended environment or use an already-authorized credential provider. Do not copy
session contents into chat. The cache is a private local file, not an OS keychain.

If an authorized credential provider is already available, unattended commands can
instead use `DEADTREES_ACCESS_TOKEN` (no automatic refresh), or `DEADTREES_EMAIL`
and `DEADTREES_PASSWORD` (refreshable in memory; new credentials are not saved).
These environment variables take precedence over the cache, so remove stale
provider overrides when intending to use the human's new login.

Onboarding limitation: `login` requires an existing account able to authenticate
with email/password. It does not implement sign-up, OAuth/device login, password
reset or MFA challenge handling. If that route is unavailable, the human must
resolve account access through the platform's normal account flow; the agent must
not ask them to paste secrets as a workaround.

Never pass passwords/tokens in command arguments, repository files or logs.
The built-in production target is `https://data2.deadtrees.earth/api/v1/` with
`https://supabase.deadtrees.earth`. Any `--api-url` override requires explicit
`DEADTREES_SUPABASE_URL` and `DEADTREES_SUPABASE_KEY`. Verify they belong together.
Only loopback endpoints may use HTTP. No shared localhost service is selected
implicitly. Using a local URL does not prove service isolation.

### Receipts, resume and failures

Automation writes `.deadtrees-upload-agent.json` beside the data **before** upload
and keeps it after success. It binds the account, target, full SHA-256 file content
and resolved metadata. `--resume` skips confirmed uploads; changed inputs or
account require reconciliation. Exact content duplicates with identical metadata
apart from filename are skipped. Conflicting duplicate metadata requires a decision.
The receipt includes upload IDs, dataset IDs and processing-request state, never
credentials. Preserve it. Each directory represents one fixed batch: put later
contributions in a new directory with their own metadata and receipt. Do not add
new files to a completed batch or mix agent and wizard uploads in that directory.
There is no cross-directory or server-wide duplicate detection, so include only
new contributions in the new directory. Byte-offset resume is unavailable.

The current chunk endpoint appends later chunks and is **not idempotent**. Only
an explicit authentication rejection is retried after refreshing credentials.
Lost/invalid final responses, transport errors and uncertain server errors stop
without replay. A `not_uploaded` receipt means no chunk was accepted; after fixing
the cause, explicit `--resume` may retry it. Authentication rejection after an
earlier accepted chunk is unresolved and cannot be retried this way.
Interrupted/in-flight uploads or processing requests remain
unresolved until inspected. Do not delete the receipt and start again to bypass
this boundary. A crash may leave a lock: confirm the owner stopped before removing
that lock, then use `--resume` to inspect the receipt.

`--process` requests geotiff, COG, thumbnail, metadata, AOI, deadwood/treecover
models and embeddings; raw photos also request ODM. A processing request failure
preserves the uploaded dataset ID and does not automatically requeue.
`status` reads the authenticated account's `v2_statuses` row. An inaccessible row
is unknown; upload done and processing requested are not terminal completion.

| Exit | Meaning |
|---|---|
| 0 | Requested operation succeeded (inspect operation and processing state). |
| 2 | Invalid/missing options, metadata or files. |
| 3 | Authentication unavailable or rejected before submission. |
| 4 | Request failed. |
| 5 | Existing/uncertain state requires reconciliation. |

The interactive wizard retains its legacy filename-based session behavior. For
repeatable automation use the explicit unattended workflow and retained receipt.

## Development and contract evidence

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
python -m pip install build
python -m build
```

Tests use synthetic imagery and mocked HTTP; no production writes are needed.
Source and distribution exercises should run in fresh environments. Tests cover
closed stdin, offline validation, metadata failures, authentication, chunk payloads,
uncertain finalization, receipt resume and processing/status distinctions.

Platform contract checked against
[DeadTrees source at 4751ac9](https://github.com/Deadwood-ai/deadtrees/tree/4751ac973853e64cb032047cd6dba9fed7763043):
`api/src/routers/upload.py`, `shared/models.py`, `shared/zip_utils.py`,
`processor/src/process_odm.py` and `frontend/src/components/Upload/UploadModal.tsx`.
This is source compatibility evidence; deployment and real contributor processing
remain separate acceptance checks. No release is implied by local validation.
