"""Template creation wizard for metadata files."""

from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm

from .validation import find_uploadable_files, GEOTIFF_EXTENSIONS, ZIP_EXTENSIONS
from .validate_geotiff import extract_date_from_geotiff
from .validate_zip import extract_date_from_zip
from .models import LicenseEnum, PlatformEnum, DataAccessEnum


console = Console()


@dataclass
class FileInfo:
	"""Information about a file for template creation."""
	filename: str
	file_path: Path
	file_type: str  # "GeoTIFF" or "ZIP"
	detected_year: Optional[int] = None
	detected_month: Optional[int] = None
	detected_day: Optional[int] = None
	confirmed_year: Optional[int] = None
	confirmed_month: Optional[int] = None
	confirmed_day: Optional[int] = None


def scan_files_with_dates(data_path: Path) -> List[FileInfo]:
	"""
	Scan files and extract dates from metadata.
	
	Args:
		data_path: Path to directory or single file
	
	Returns:
		List of FileInfo with detected dates
	"""
	files, file_types = find_uploadable_files(data_path)
	
	file_infos = []
	
	console.print("\n[bold]Scanning files for date metadata...[/bold]")
	
	for file_path in files:
		file_type = file_types[file_path.name]
		
		# Extract date based on file type
		if file_type == "GeoTIFF":
			year, month, day = extract_date_from_geotiff(file_path)
		else:  # ZIP
			year, month, day = extract_date_from_zip(file_path)
		
		file_infos.append(FileInfo(
			filename=file_path.name,
			file_path=file_path,
			file_type=file_type,
			detected_year=year,
			detected_month=month,
			detected_day=day,
		))
	
	return file_infos


def format_date(year: Optional[int], month: Optional[int], day: Optional[int]) -> str:
	"""Format date parts into a string."""
	if not year:
		return "-"
	parts = [str(year)]
	if month:
		parts.append(f"{month:02d}")
	if day:
		parts.append(f"{day:02d}")
	return "-".join(parts)


def show_detected_dates(file_infos: List[FileInfo]) -> None:
	"""Display detected dates in a table."""
	table = Table(title="Detected Acquisition Dates")
	table.add_column("File", style="cyan", max_width=40)
	table.add_column("Type", style="dim")
	table.add_column("Detected Date", justify="center")
	table.add_column("Status", justify="center")
	
	for info in file_infos:
		date_str = format_date(info.detected_year, info.detected_month, info.detected_day)
		status = "[green]✓ Found[/green]" if info.detected_year else "[yellow]⚠ Not found[/yellow]"
		table.add_row(info.filename[:40], info.file_type, date_str, status)
	
	console.print(table)


def confirm_dates(file_infos: List[FileInfo]) -> List[FileInfo]:
	"""Confirm or edit dates for each file."""
	console.print("\n[bold]Confirm or edit dates for each file:[/bold]")
	console.print("[dim]Press Enter to accept, or type a new date (YYYY-MM-DD, YYYY-MM, or YYYY)[/dim]\n")
	
	for info in file_infos:
		date_str = format_date(info.detected_year, info.detected_month, info.detected_day)
		status = f"[green]{date_str}[/green]" if info.detected_year else "[yellow]No date found[/yellow]"
		console.print(f"  {info.filename}: {status}")
		
		user_input = Prompt.ask("    Date", default=date_str if info.detected_year else "")
		
		if user_input:
			info.confirmed_year, info.confirmed_month, info.confirmed_day = parse_date_input(user_input)
		else:
			info.confirmed_year = info.detected_year
			info.confirmed_month = info.detected_month
			info.confirmed_day = info.detected_day
		
		while not info.confirmed_year:
			console.print("    [red]Year is required![/red]")
			user_input = Prompt.ask("    Enter date (YYYY-MM-DD, YYYY-MM, or YYYY)")
			if user_input:
				info.confirmed_year, info.confirmed_month, info.confirmed_day = parse_date_input(user_input)
	
	return file_infos


def parse_date_input(date_str: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
	"""Parse a date string into year, month, day (supports YYYY-MM-DD, YYYY-MM, YYYY)."""
	date_str = date_str.strip()
	parts = date_str.split('-') if '-' in date_str else [date_str]
	
	try:
		year = int(parts[0]) if parts[0] else None
		month = int(parts[1]) if len(parts) > 1 else None
		day = int(parts[2]) if len(parts) > 2 else None
		return year, month, day
	except (ValueError, IndexError):
		return None, None, None


def ask_global_values() -> Dict[str, str]:
	"""
	Ask for values that apply to all files.
	
	Returns:
		Dict with license, platform, authors, data_access
	"""
	console.print("\n[bold]Enter values that apply to ALL files:[/bold]\n")
	
	# License
	license_options = [e.value for e in LicenseEnum]
	console.print(f"  Available licenses: {', '.join(license_options)}")
	license_val = Prompt.ask("  License", default="CC BY")
	
	# Platform
	platform_options = [e.value for e in PlatformEnum]
	console.print(f"  Available platforms: {', '.join(platform_options)}")
	platform_val = Prompt.ask("  Platform", default="drone")
	
	# Authors
	authors_val = Prompt.ask("  Authors (semicolon-separated)", default="")
	
	# Data access
	access_options = [e.value for e in DataAccessEnum]
	console.print(f"  Available access levels: {', '.join(access_options)}")
	access_val = Prompt.ask("  Data access", default="public")
	
	return {
		"license": license_val,
		"platform": platform_val,
		"authors": authors_val,
		"data_access": access_val,
	}


def create_template_dataframe(
	file_infos: List[FileInfo],
	global_values: Dict[str, str],
) -> pd.DataFrame:
	"""
	Create a template DataFrame from file info and global values.
	
	Args:
		file_infos: List of FileInfo with confirmed dates
		global_values: Dict with global column values
	
	Returns:
		DataFrame ready to save as CSV
	"""
	rows = []
	
	for info in file_infos:
		row = {
			"filename": info.filename,
			"license": global_values["license"],
			"platform": global_values["platform"],
			"authors": global_values["authors"],
			"acquisition_year": info.confirmed_year,
			"acquisition_month": info.confirmed_month,
			"acquisition_day": info.confirmed_day,
			"data_access": global_values["data_access"],
			"additional_information": "",
			"citation_doi": "",
		}
		rows.append(row)
	
	return pd.DataFrame(rows)


def save_template(df: pd.DataFrame, output_path: Path) -> None:
	"""Save template DataFrame to CSV."""
	df.to_csv(output_path, index=False)
	console.print(f"\n[green]✓[/green] Template saved to: {output_path}")


def run_template_wizard(data_path: Path, output_path: Optional[Path] = None) -> Path:
	"""
	Run the complete template creation wizard.
	
	Args:
		data_path: Path to directory or single file
		output_path: Optional output path for template (default: data_path/metadata.csv)
	
	Returns:
		Path to created template file
	"""
	console.print("\n[bold blue]Template Creation Wizard[/bold blue]")
	console.print("=" * 40)
	
	# 1. Scan files and detect dates
	file_infos = scan_files_with_dates(data_path)
	
	if not file_infos:
		console.print("[red]No uploadable files found![/red]")
		raise ValueError("No files to create template for")
	
	console.print(f"\nFound [bold]{len(file_infos)}[/bold] files")
	
	# 2. Show detected dates
	show_detected_dates(file_infos)
	
	# 3. Ask for global values
	global_values = ask_global_values()
	
	# 4. Confirm dates for each file
	file_infos = confirm_dates(file_infos)
	
	# 5. Create template
	df = create_template_dataframe(file_infos, global_values)
	
	# 6. Determine output path
	if output_path is None:
		if data_path.is_file():
			output_path = data_path.parent / "metadata.csv"
		else:
			output_path = data_path / "metadata.csv"
	
	# 7. Save template
	save_template(df, output_path)
	
	# 8. Show preview
	console.print("\n[bold]Template preview:[/bold]")
	console.print(df.to_string(index=False))
	
	return output_path
