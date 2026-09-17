---
name: deadtrees-upload
description: Validate metadata and RGB GeoTIFF or raw-drone ZIP inputs, install and use the DeadTrees Upload CLI, and submit or inspect explicitly authorized deadtrees.earth uploads. Use for contribution workflows, not preprocessing or multispectral analysis.
---

# DeadTrees uploads

Deadtrees.earth hosts aerial forest imagery and derives orthomosaics, map products,
and deadwood/tree-cover predictions. Contributors retain responsibility for
accurate authorship, capture dates, license, access level and permission to share.
An upload is not evidence that reconstruction or model processing succeeded.

## Decide what the contributor has

- Georeferenced RGB orthomosaic: upload the GeoTIFF directly. The CLI checks
  embedded CRS, transform and RGB color interpretations; a fourth alpha band is
  allowed. It does not upload sidecars. More bands, elevation/indices, grayscale,
  false-color or unclear band semantics need clarification. Do not reinterpret
  bands or invent a CRS to make validation pass.
- Raw RGB drone photographs: upload their ZIP directly; the platform runs ODM
  when processing is requested. Preprocessing is not required. Use Store/Deflate
  ZIP compression, at least three RGB candidates surviving the worker filters and sufficient overlapping,
  geotagged photographs for reconstruction. Current worker excludes images
  <=100 KiB. Local success cannot prove flight geometry or reconstruction quality.
- Mixed RGB/multispectral ZIP: the platform excludes filenames containing
  `_MS_`. Report that warning and confirm the intended RGB subset; never promise
  multispectral processing or automatically rewrite the contributor's archive.
  Other ambiguous sensor layouts and RAW/DNG decoding require clarification.
  A file extension accepted as an ODM candidate is not proof of usable RGB data.

## Enter through the repository

Given `https://github.com/Deadwood-ai/deadtrees-upload`, clone it into a chosen
working directory, select the agreed revision, and record `git rev-parse HEAD`.
Keep this checkout: skill, CLI, helper and README must come from that same revision.
No separate skill installation or wheel distribution is required. Read the
[repository README](../../../README.md) for setup and field values. This link is
relative to **this SKILL.md**; do not resolve it against the shell's current directory.
All local resources are inside the repository. Other agents can read the absolute
skill path directly even when their current directory is elsewhere.

Set `DT_UPLOAD_REPO` to the absolute checkout path (for example `DT_UPLOAD_REPO="$PWD"`
after changing into the checkout), then install from that path:

```sh
python3 -m venv "$DT_UPLOAD_REPO/.venv"
"$DT_UPLOAD_REPO/.venv/bin/python" -m pip install "$DT_UPLOAD_REPO"
"$DT_UPLOAD_REPO/.venv/bin/deadtrees-upload" --help
"$DT_UPLOAD_REPO/.venv/bin/deadtrees-upload" login --help
"$DT_UPLOAD_REPO/.venv/bin/deadtrees-upload" status --help
```

Reinstall from the checkout if its revision changes; do not mix a downloaded skill
with a differently installed CLI. On Windows use `.venv\Scripts\python.exe` and
`.venv\Scripts\deadtrees-upload.exe`. No global Python or personal agent config
changes are needed. The README includes the repository-URL clone commands.

## Start with the contributor's folder

Use the [draft helper](scripts/prepare_metadata.py), which reuses CLI discovery,
validation, date extraction and template functions:

```sh
"$DT_UPLOAD_REPO/.venv/bin/python" \
  "$DT_UPLOAD_REPO/.agents/skills/deadtrees-upload/scripts/prepare_metadata.py" \
  --data-dir DATA --output metadata-draft.csv
```

Use absolute input/output paths when working outside the contributor directory;
`.xlsx` is also supported. The helper writes a new incomplete draft and refuses
overwrite. Its JSON inventory contains file sizes/types, validation findings and
embedded date **candidates**, and lists entries excluded from top-level discovery.
Draft creation does not mean the files are valid. Report invalid/unsupported and
unselected inputs rather than silently omitting them. Do not recurse or upload
additional directories without establishing their intended scope.

Ask the contributor for missing consequential decisions: authorship, permission
and license, visibility, actual capture platform, and acquisition date at the
precision they know. Embedded TIFF timestamps can reflect export time; sampled
JPEG EXIF may not represent a whole flight. Confirm those candidates before filling
the date columns. Do not infer dates from file modification time or filenames,
or infer drone/airborne or RGB sensor meaning from extensions/band counts alone.
Use reliable supplied metadata when available and state its provenance. Preserve
unknowns as blank in the draft until resolved; then fill CSV/XLSX with the confirmed
values. Never substitute guessed values just to obtain a passing validation.

For loose drone photographs or nested flights, clarify grouping first. If creating
a ZIP is authorized, package the agreed original photographs with Store/Deflate,
preserve names/EXIF and originals, and keep separate flights/areas separate. This
is packaging, not a requirement to preprocess imagery. Ambiguous RGB/multispectral
sets need the contributor's decision about the intended subset before proceeding.

## Validate and present the plan

Use one top-level data directory or one file. Metadata is CSV or XLSX; filenames
must uniquely match every selected file; a single-file selection needs a matching
metadata sheet containing only that file. Prefer canonical columns:
`filename,license,platform,authors,acquisition_year,data_access`.
Authors use semicolons. Read the README for supported values and optional fields.
Ask for missing authors, license, date and access intent; do not fabricate them.
Unattended validation requires an explicit `data_access` value for each row;
missing or blank visibility fails. The human wizard retains its established default.

```sh
"$DT_UPLOAD_REPO/.venv/bin/deadtrees-upload" --data-dir DATA --metadata metadata.csv --dry-run --json
```

This command is offline and does not authenticate, upload, create cache files or
alter receipts. Use its resolved metadata, per-file errors and warnings to explain
what would be submitted. Unmatched files, duplicate metadata and invalid inputs
fail the whole automated batch. Separate dates are authoritative; automation does
not fill missing month/day from unrelated embedded timestamps. Preserve originals.

## Authenticate and submit only within authorization

For first-time login, hand this command to the **human's own terminal**, on the
same machine/OS account where the agent will run:

```sh
"$DT_UPLOAD_REPO/.venv/bin/deadtrees-upload" login
```

The human enters email and a masked password there, never in chat. Wait for their
confirmation that login succeeded; do not capture the password through tools or
transcripts. This command saves a refreshable session using the existing login
route and stops without uploading. Subsequent agent validation/upload/status
commands use that cache under the same OS user and API target. The README explains
cache scope and provider overrides. Login success alone is not upload authorization.

An existing authorized credential provider may instead populate environment
variables `DEADTREES_ACCESS_TOKEN` or `DEADTREES_EMAIL` plus `DEADTREES_PASSWORD`.
Never put secrets in arguments, chat, logs, tracked files or metadata. Provider
variables override cached sessions. A bearer token cannot refresh itself; cached
and password sessions can. Do not inspect or display cached token values.

If the agent runs remotely, in a container, or as another OS user, the human's
local cache is not automatically available: use login in the actual execution
environment or an authorized credential provider. The current login requires an
existing email/password account; it does not implement account creation, OAuth,
device login or MFA challenges. Explain an unavailable account route and let the
human resolve it through the platform; do not ask for secrets in chat as a fallback.

Custom API targets require both `DEADTREES_SUPABASE_URL` and
`DEADTREES_SUPABASE_KEY`; confirm they belong to the same intended environment.
Local endpoints are not automatically isolated. Testing must use mocks or a
verified isolated service, never the default shared stack or production writes.

Once the user has authorized the particular data, metadata and target:

```sh
"$DT_UPLOAD_REPO/.venv/bin/deadtrees-upload" --data-dir DATA --metadata metadata.csv --non-interactive --yes --json
```

Add `--process` only when platform processing is also authorized. It requests the
current normal imagery pipeline; `processing: requested` is not completion.

Retain `.deadtrees-upload-agent.json` beside the data. Use the same command with
`--resume` to skip confirmed uploads or request explicitly authorized processing
for uploaded data. The receipt binds account, target, file content and metadata.
Treat each directory as a fixed batch. Put later, genuinely new contributions in
a new directory with separate metadata and receipt; preserve the old receipt.
Do not switch to the wizard to bypass an agent receipt or lock. Only a confirmed
`not_uploaded` state permits an explicit `--resume` retry after fixing its cause.
No byte-offset resume or server-wide duplicate prevention is available.

Exit codes: `0` requested command succeeded; `2` inputs/options invalid;
`3` authentication unavailable; `4` request failed; `5` reconciliation required.
The server appends chunks and finalization is not idempotent. After code 5,
interruption or a lost response, stop and inspect the receipt's upload/dataset IDs.
Do not delete the receipt, automatically retry chunks, re-upload or requeue.
A stale lock requires confirming its process stopped before removing the lock.
Resolve unknown outcomes through authorized platform inspection or the owner.

## Track without mutation

```sh
"$DT_UPLOAD_REPO/.venv/bin/deadtrees-upload" status DATASET_ID --json
```

This reads `v2_statuses` under the authenticated account. Report upload flags,
processing flags and errors separately. Missing/inaccessible status is unknown.
Do not equate an accepted upload, queue request or idle state with completed
products. Use the dataset ID and actual returned flags in the completion message.
