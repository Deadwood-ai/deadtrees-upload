# DeadTrees Upload CLI

Batch upload datasets to [deadtrees.earth](https://deadtrees.earth).

## Features

- **Interactive CLI** - Step-by-step guided upload process
- **Batch uploads** - Upload multiple GeoTIFFs or raw image ZIPs at once
- **Auto token refresh** - Handles long-running uploads without re-authentication
- **Resume support** - Automatically resume interrupted uploads
- **Duplicate detection** - Prevents uploading the same file twice
- **File validation** - Validates GeoTIFFs (CRS, bands) and ZIPs (GPS data) before upload
- **Automatic processing** - Triggers the processing pipeline after upload

## Installation

Install from source:

```bash
git clone https://github.com/Deadwood-ai/deadtrees-upload.git
cd deadtrees-upload
pip install -e .
```

Or install directly from GitHub:

```bash
pip install git+https://github.com/Deadwood-ai/deadtrees-upload.git
```

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
  - Valid Coordinate Reference System (CRS)
  - At least 3 bands (RGB)
  - Proper georeferencing

### ZIP Files (Raw Drone Images)
- Extension: `.zip`
- Should contain raw drone images for ODM processing
- Supported image formats: JPEG, PNG, TIFF, DNG, RAW, CR2, NEF, ARW
- **Recommendation:** Images should have GPS coordinates in EXIF for best ODM results

## Resume Interrupted Uploads

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
