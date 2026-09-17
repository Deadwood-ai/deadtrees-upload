"""Inventory a contributor folder and write an incomplete metadata draft, offline."""
import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys

from deadtrees_upload.template import scan_files_with_dates, create_template_dataframe
from deadtrees_upload.validation import validate_file, ValidationError


def prepare(data_path: Path, output_path: Path) -> dict:
    """Reuse CLI discovery/extraction and templates; never infer contributor choices."""
    if output_path.suffix.lower() not in {".csv", ".xlsx"}:
        raise ValueError("Draft output must be .csv or .xlsx")
    if output_path.exists():
        raise ValueError("Output already exists; choose a new draft path to preserve it")
    with redirect_stdout(sys.stderr):
        infos = scan_files_with_dates(data_path)
    if not infos:
        raise ValueError("No top-level GeoTIFF or ZIP candidates. Loose drone photos need an agreed ZIP grouping; subfolders are not scanned")
    inventory = []
    for info in infos:
        validation, _ = validate_file(info.file_path)
        inventory.append({
            "filename": info.filename, "file_type": info.file_type,
            "size_bytes": info.file_path.stat().st_size,
            "is_valid": validation.is_valid, "errors": validation.errors,
            "warnings": validation.warnings,
            "embedded_date_candidate": [info.detected_year, info.detected_month, info.detected_day],
        })
    # Even embedded date tags can be export times or a non-representative sample.
    # Keep candidates in the inventory for confirmation, never silently in the CSV.
    draft = create_template_dataframe(infos, {"license": "", "platform": "", "authors": "", "data_access": ""})
    if output_path.suffix.lower() == ".xlsx":
        import pandas as pd
        with output_path.open("xb") as stream, pd.ExcelWriter(stream, engine="openpyxl") as writer:
            draft.to_excel(writer, index=False)
            # Filenames are literal data, including names beginning with '='.
            for row in writer.sheets["Sheet1"]:
                for cell in row:
                    if isinstance(cell.value, str):
                        cell.data_type = "s"
    else:
        with output_path.open("x", encoding="utf-8", newline="") as stream:
            draft.to_csv(stream, index=False)
    selected = {info.file_path.resolve() for info in infos}
    unselected = sorted(p.name for p in data_path.iterdir() if p.resolve() not in selected and p.resolve() != output_path.resolve()) if data_path.is_dir() else []
    return {"operation": "prepare_metadata", "draft": str(output_path), "files": inventory,
            "unselected_entries": unselected,
            "needs_confirmation": ["authors", "license", "platform", "acquisition_year", "data_access"],
            "note": "Draft only; confirm embedded date candidates and complete metadata before CLI validation"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.data_dir.expanduser().resolve(), args.output.expanduser().resolve())
    except (ValueError, OSError, ValidationError) as error:
        print(json.dumps({"operation": "prepare_metadata", "errors": [str(error)]}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
