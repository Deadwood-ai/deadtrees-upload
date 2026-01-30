# DeadTrees Upload CLI

Batch upload datasets to [deadtrees.earth](https://deadtrees.earth).

## Features

- **Interactive CLI** - Step-by-step guided upload process with retry on errors
- **Batch uploads** - Upload multiple GeoTIFFs or raw image ZIPs at once
- **Single file support** - Upload individual files directly (not just directories)
- **Template wizard** - Auto-create metadata files with date detection from files
- **Auto token refresh** - Handles long-running uploads without re-authentication
- **Resume support** - Automatically resume interrupted uploads
- **Duplicate detection** - Prevents uploading the same file twice
- **File validation** - Validates GeoTIFFs (CRS, bands) and ZIPs (GPS data) before upload
- **Automatic date extraction** - Detects acquisition dates from GeoTIFF metadata and EXIF
- **Automatic processing** - Triggers the processing pipeline after upload

## How It Works

The CLI guides you through a 6-step process:

```
┌──────────────────────────────────────────────────────────────────┐
│                    DeadTrees Upload Workflow                     │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Step 1: Authentication                                          │
│  └─> Login with your deadtrees.earth email/password              │
│                                                                  │
│  Step 2: Data Directory                                          │
│  └─> Point to a folder with .tif/.zip files (or a single file)   │
│                                                                  │
│  Step 3: Metadata File                                           │
│  └─> Provide a CSV/Excel with file info, or use Template Wizard  │
│                                                                  │
│  Step 4: Column Mapping                                          │
│  └─> Map your CSV columns to required fields (auto-detected)     │
│                                                                  │
│  Step 5: Validation                                              │
│  └─> Validates files + metadata before upload                    │
│                                                                  │
│  Step 6: Upload & Process                                        │
│  └─> Chunked upload with progress bar, then triggers processing  │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### What Happens After Upload?

Once files are uploaded, the CLI automatically triggers the appropriate processing pipeline:

| File Type | Processing Pipeline |
|-----------|---------------------|
| **GeoTIFF** (`.tif`) | `geotiff` → `cog` → `thumbnail` → `metadata` → `deadwood` → `treecover` |
| **Raw Images** (`.zip`) | `odm_processing` → (same as GeoTIFF after ortho generation) |

- **GeoTIFFs** are converted to Cloud-Optimized GeoTIFFs (COGs), thumbnails are generated, and AI segmentation runs
- **ZIP files** containing raw drone images are processed through OpenDroneMap (ODM) to generate orthomosaics first

## Installation

**Recommended: Use a fresh virtual environment** to avoid dependency conflicts.

```bash
# Create and activate a virtual environment
python -m venv deadtrees-env
source deadtrees-env/bin/activate  # Linux/Mac
# or: deadtrees-env\Scripts\activate  # Windows

# Install the package
pip install git+https://github.com/Deadwood-ai/deadtrees-upload.git
```

Or install from source:

```bash
git clone https://github.com/Deadwood-ai/deadtrees-upload.git
cd deadtrees-upload
pip install -e .
```

### Troubleshooting: NumPy Version Conflict

If you see an error like `A module compiled using NumPy 1.x cannot be run in NumPy 2.x`, this means your environment has conflicting package versions.

**Solution:** Use a fresh virtual environment (see above) or:

```bash
# Option 1: Upgrade all packages
pip install --upgrade pandas pyarrow numpy

# Option 2: Downgrade numpy
pip install "numpy<2"
```

This commonly happens with Anaconda environments where packages get out of sync.

## Quick Start

### Interactive Mode

Simply run the CLI and follow the prompts:

```bash
deadtrees-upload
```

The CLI will guide you through:
1. Authentication (email/password)
2. Selecting your data directory
3. Providing a metadata file
4. Validating files and metadata
5. Uploading and triggering processing

### Single File Upload

You can upload a single file directly:

```bash
deadtrees-upload --data-dir /path/to/ortho.tif --metadata metadata.csv
```

### Template Wizard

If you don't have a metadata file, the CLI will offer to create one automatically:

```
┌─────────────────────────────────────────────────────────────────┐
│                   Template Creation Wizard                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. File Scanning                                               │
│     └─> Finds all .tif and .zip files in your directory         │
│                                                                 │
│  2. Date Detection                                              │
│     └─> Extracts dates from:                                    │
│         • GeoTIFF metadata (TIFFTAG_DATETIME)                   │
│         • JPEG EXIF in ZIPs (DateTimeOriginal)                  │
│                                                                 │
│  3. Date Review Table                                           │
│     ┌──────────────────────┬──────┬───────────────┬──────────┐  │
│     │ File                 │ Type │ Detected Date │ Status   │  │
│     ├──────────────────────┼──────┼───────────────┼──────────┤  │
│     │ ortho_2024.tif       │ TIF  │ 2024-06-15    │ ✓ Found  │  │
│     │ raw_images.zip       │ ZIP  │ 2024-07-20    │ ✓ Found  │  │
│     │ old_survey.tif       │ TIF  │ -             │ ⚠ None   │  │
│     └──────────────────────┴──────┴───────────────┴──────────┘  │
│                                                                 │
│  4. Global Values (applied to all files)                        │
│     └─> License, Platform, Authors, Data Access                 │
│                                                                 │
│  5. Date Confirmation                                           │
│     └─> Confirm or edit each file's date (year is required)     │
│                                                                 │
│  6. Save Template                                               │
│     └─> Saves metadata.csv ready for upload                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Example session:**

```
Found 6 files

              Detected Acquisition Dates
┌────────────────────────────────┬──────┬───────────────┬──────────┐
│ File                           │ Type │ Detected Date │ Status   │
├────────────────────────────────┼──────┼───────────────┼──────────┤
│ 20160215_CA_Marin_Hill_88.zip  │ ZIP  │ 2016-02-15    │ ✓ Found  │
│ 20160213_CA_Marin_Brickyard.zip│ ZIP  │ 2016-02-13    │ ✓ Found  │
└────────────────────────────────┴──────┴───────────────┴──────────┘

Enter values that apply to ALL files:
License [CC BY]: CC BY
Platform [drone]: drone
Authors: Research Team
Data access [public]: public

✓ Template saved to: /path/to/data/metadata.csv
```

### Non-Interactive Mode

Provide all options via command line:

```bash
deadtrees-upload \
  --data-dir /path/to/files \
  --metadata /path/to/metadata.csv \
  --email user@example.com
```

### Dry Run

Validate without uploading:

```bash
deadtrees-upload --dry-run
```

### Custom API URL (Development)

For testing against a local or staging environment:

```bash
deadtrees-upload --api-url http://localhost:8080/api/v1/
```

## Metadata File Format

Create a CSV or Excel file with the following columns:

### Required Columns

| Column | Description | Valid Values |
|--------|-------------|--------------|
| `filename` | Name of the file (must match actual file) | Any string |
| `license` | Data license | `CC BY`, `CC BY-SA`, `CC BY-NC-SA`, `CC BY-NC`, `MIT` |
| `platform` | Capture platform | `drone`, `airborne` |
| `authors` | Author names (semicolon-separated) | e.g., `John Smith; Jane Doe` |
| `acquisition_date` OR `acquisition_year` | Date of data capture (required) | Date: `2024-06-15`, `2024-06`, `2024` / Year: `1980-2099` |

### Optional Columns

| Column | Description | Valid Values |
|--------|-------------|--------------|
| `acquisition_month` | Month of data capture | 1-12 |
| `acquisition_day` | Day of data capture | 1-31 |
| `data_access` | Access level | `public` (default), `private`, `viewonly` |
| `additional_information` | Additional notes | Free text |
| `citation_doi` | DOI if published | e.g., `10.1234/example` |

### Example CSV

```csv
filename,license,platform,authors,acquisition_date,data_access,additional_information
ortho_001.tif,CC BY,drone,John Smith; Jane Doe,2024-06-15,public,Forest survey site A
ortho_002.tif,CC BY,drone,John Smith,2024-06-16,public,
raw_images.zip,CC BY-SA,drone,Research Team,2024-07,public,Raw drone images for ODM
```

**Note:** The `acquisition_date` column is **required**. You can provide it as:
- Full date: `2024-06-15`
- Year and month: `2024-06`
- Year only: `2024`

Alternatively, you can use separate `acquisition_year`, `acquisition_month`, `acquisition_day` columns.

A template is included in `templates/metadata_template.csv`.

## Supported File Types

### GeoTIFF Files (Orthomosaics)
- Extensions: `.tif`, `.tiff`, `.geotiff`
- **Requirements:**
  - Valid Coordinate Reference System (CRS) - `LOCAL_CS` and engineering CRS are rejected
  - At least 3 bands (RGB)
  - Proper georeferencing (transform must not be identity)

### ZIP Files (Raw Drone Images)
- Extension: `.zip`
- Should contain raw drone images for ODM processing
- Supported image formats: JPEG, PNG, TIFF, DNG, RAW, CR2, NEF, ARW
- **Recommendation:** Images should have GPS coordinates in EXIF for best ODM results

## Validation Details

Before upload, the CLI validates each file:

### GeoTIFF Validation

| Check | Description | Error If Failed |
|-------|-------------|-----------------|
| CRS | Must have a valid coordinate reference system | `Invalid CRS: LOCAL_CS not supported` |
| Bands | Must have at least 3 bands (RGB) | `Insufficient bands: found 1, need 3+` |
| Georeferencing | Must have proper transform (not identity) | `Missing georeferencing` |

### ZIP Validation

| Check | Description | Warning If Failed |
|-------|-------------|-------------------|
| Image count | Must contain image files | `No images found in ZIP` |
| GPS data | Sample images checked for GPS EXIF | `⚠ No GPS data - ODM may fail` |

**Note:** ZIP validation issues are warnings, not errors. You can still upload, but ODM processing may fail without GPS data.

## Error Handling & Retry

The CLI is designed to be fault-tolerant:

### Metadata Errors

If there's an error in your metadata file (missing required fields, invalid values), the CLI will:
1. Show you exactly what's wrong
2. Ask if you want to fix the file and retry
3. Let you edit the file externally (in any editor)
4. Press Enter to re-read the file without restarting the CLI

```
✗ Validation error: Missing required field 'acquisition_year' for file ortho.tif

Would you like to fix the metadata and retry? [y/n]: y

Fix the metadata file and press Enter when ready...
```

### Resume Interrupted Uploads

If an upload is interrupted (network failure, crash, etc.), the CLI automatically saves progress to `.deadtrees-upload-session.json` in your data directory. 

On the next run, you'll be prompted to resume:

```
┌─ Previous Session ─────────────────────┐
│ Found incomplete upload session        │
│ Started: 2024-06-15T10:30:00           │
│ Completed: 5/20                        │
│ Failed: 1                              │
└────────────────────────────────────────┘
Resume previous session? [y/n]:
```

### Duplicate Detection

The CLI tracks uploaded files by computing a hash of each file. If you try to upload the same file again:
- Within the same session: Automatically skipped
- Across sessions: Warned and prompted to skip or re-upload

## CLI Reference

```
Usage: deadtrees-upload [OPTIONS] COMMAND [ARGS]...

Options:
  -d, --data-dir PATH   Path to directory containing files to upload
  -m, --metadata PATH   Path to metadata CSV/Excel file
  -e, --email TEXT      Email for authentication
  --api-url TEXT        API URL (for development/testing)
  --dry-run             Validate without uploading
  --help                Show this message and exit

Commands:
  version  Show version information
```

## Development

### Setup

```bash
git clone https://github.com/Deadwood-ai/deadtrees-upload.git
cd deadtrees-upload
pip install -e ".[dev]"
```

### Running Tests

```bash
pytest
```

### Testing Against Local Environment

```bash
# Start the deadtrees test stack
cd ../deadtrees
deadtrees dev start

# Run the CLI against local API
deadtrees-upload --api-url http://localhost:8080/api/v1/
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Links

- **Website**: [deadtrees.earth](https://deadtrees.earth)
- **Documentation**: [docs.deadtrees.earth](https://docs.deadtrees.earth)
- **Issues**: [GitHub Issues](https://github.com/Deadwood-ai/deadtrees-upload/issues)
