"""Interactive prompts for CLI."""

from pathlib import Path
from typing import Optional, List

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

from .auth import (
	create_auth_session,
	AuthError,
	AuthSession,
	get_cached_session,
	save_auth_session,
)
from .metadata import (
	suggest_column_matches,
	get_valid_values_help,
	REQUIRED_COLUMNS,
)
from .validation import find_uploadable_files, ValidationError
from .dedup import UploadSessionState, get_session_file_path, find_existing_session
from .display import print_step


console = Console()

# Supabase configuration
PROD_SUPABASE_URL = "https://supabase.deadtrees.earth"
PROD_SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.ewogICJyb2xlIjogImFub24iLAogICJpc3MiOiAic3VwYWJhc2UiLAogICJpYXQiOiAxNzQwODcwMDAwLAogICJleHAiOiAxODk4NjM2NDAwCn0.A3HdTofLNcrRrtDDbDAP9kRBobxXqnUKB6IYHvM6da4"

LOCAL_SUPABASE_URL = "http://localhost:54321"
LOCAL_SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0"


def get_supabase_config(api_url: str) -> tuple[str, str]:
	"""Get Supabase URL and key based on API URL."""
	if "localhost" in api_url or "127.0.0.1" in api_url:
		return LOCAL_SUPABASE_URL, LOCAL_SUPABASE_KEY
	return PROD_SUPABASE_URL, PROD_SUPABASE_KEY


def authenticate(api_url: str) -> AuthSession:
	"""Prompt for credentials and authenticate with session support."""
	print_step(1, "Authentication")
	
	cached_session = get_cached_session(api_url)
	if cached_session:
		console.print("[green]✓[/green] Using stored credentials")
		return cached_session
	
	supabase_url, supabase_key = get_supabase_config(api_url)
	if "localhost" in api_url:
		console.print("[dim]Using local Supabase for authentication[/dim]")
	
	email = Prompt.ask("[bold]Email[/bold]")
	password = Prompt.ask("[bold]Password[/bold]", password=True)
	
	with console.status("[bold green]Authenticating...[/bold green]"):
		try:
			session = create_auth_session(
				email=email,
				password=password,
				supabase_url=supabase_url,
				supabase_key=supabase_key,
			)
			console.print(f"[green]✓[/green] Authenticated as [bold]{email}[/bold]")
			console.print("[dim]Token will auto-refresh during long uploads[/dim]")
			try:
				save_auth_session(session, api_url)
			except Exception:
				console.print("[yellow]![/yellow] Could not persist credentials")
			return session
		except AuthError as e:
			console.print(f"[red]✗[/red] Authentication failed: {e}")
			raise typer.Exit(1)


def select_data_directory() -> Path:
	"""Prompt for data directory with path autocomplete."""
	print_step(2, "Select Data Directory")
	
	console.print("[dim]Tip: Use Tab for autocomplete, start with ~ for home directory[/dim]")
	console.print()
	
	while True:
		try:
			import questionary
			path_str = questionary.path(
				"Enter path to data directory:",
				only_directories=True,
			).ask()
			
			if path_str is None:  # User cancelled
				raise typer.Exit(0)
		except Exception:
			# Fallback to simple prompt if questionary.path fails
			path_str = Prompt.ask("[bold]Enter path to data directory[/bold]")
		
		path = Path(path_str).expanduser().resolve()
		
		if not path.exists():
			console.print(f"[red]✗[/red] Directory does not exist: {path}")
			continue
		
		if not path.is_dir():
			console.print(f"[red]✗[/red] Path is not a directory: {path}")
			continue
		
		try:
			files, file_types = find_uploadable_files(path)
		except ValidationError as e:
			console.print(f"[red]✗[/red] {e}")
			continue
		
		if not files:
			console.print(f"[yellow]![/yellow] No uploadable files found (GeoTIFF or ZIP)")
			if not Confirm.ask("Try a different directory?"):
				raise typer.Exit(1)
			continue
		
		# Count by type
		geotiff_count = sum(1 for t in file_types.values() if t == "GeoTIFF")
		zip_count = sum(1 for t in file_types.values() if t == "ZIP")
		
		console.print(f"[green]✓[/green] Found [bold]{len(files)}[/bold] files:")
		if geotiff_count:
			console.print(f"  • {geotiff_count} GeoTIFF files")
		if zip_count:
			console.print(f"  • {zip_count} ZIP files")
		
		return path


def find_metadata_files_in_directory(directory: Path) -> List[Path]:
	"""Find CSV and Excel files in a directory that might be metadata files."""
	metadata_files = []
	for pattern in ["*.csv", "*.xlsx", "*.xls"]:
		metadata_files.extend(directory.glob(pattern))
	return sorted(metadata_files)


def select_metadata_file(data_dir: Path) -> Path:
	"""Prompt for metadata file, auto-detecting files in data directory or creating one."""
	print_step(3, "Metadata File")
	
	# Check for metadata files in data directory
	found_files = find_metadata_files_in_directory(data_dir)
	
	# If no metadata files found, offer to create one
	if not found_files:
		console.print("[yellow]No metadata files found in data directory.[/yellow]")
		if Confirm.ask("Would you like to create a metadata template?"):
			from .template import run_template_wizard
			template_path = run_template_wizard(data_dir)
			console.print(f"\n[green]✓[/green] Template created: {template_path}")
			console.print("[dim]Please review and edit the template if needed, then press Enter to continue.[/dim]")
			Prompt.ask("Press Enter when ready")
			return template_path
	
	if found_files:
		console.print(f"[green]Found {len(found_files)} metadata file(s) in data directory:[/green]")
		for i, f in enumerate(found_files, 1):
			console.print(f"  {i}. {f.name}")
		console.print(f"  0. [dim]Enter different path[/dim]")
		console.print()
		
		while True:
			choice = Prompt.ask("Select file", default="1")
			try:
				choice_int = int(choice)
				if choice_int == 0:
					break  # Fall through to manual path entry
				if 1 <= choice_int <= len(found_files):
					selected = found_files[choice_int - 1]
					console.print(f"[green]✓[/green] Using {selected.name}")
					return selected
			except ValueError:
				pass
			console.print("[red]Invalid choice[/red]")
	
	# Show valid values for reference
	valid_values = get_valid_values_help()
	console.print("[dim]Valid values for enum fields:[/dim]")
	for field, values in valid_values.items():
		console.print(f"  • [bold]{field}[/bold]: {', '.join(values)}")
	console.print()
	console.print("[dim]Tip: Use Tab for autocomplete[/dim]")
	console.print()
	
	while True:
		try:
			import questionary
			path_str = questionary.path(
				"Enter path to metadata file (CSV or Excel):",
				only_directories=False,
			).ask()
			
			if path_str is None:  # User cancelled
				raise typer.Exit(0)
		except Exception:
			# Fallback to simple prompt
			path_str = Prompt.ask("[bold]Enter path to metadata file (CSV or Excel)[/bold]")
		
		path = Path(path_str).expanduser().resolve()
		
		if not path.exists():
			console.print(f"[red]✗[/red] File does not exist: {path}")
			continue
		
		if path.suffix.lower() not in [".csv", ".xlsx", ".xls"]:
			console.print(f"[red]✗[/red] Unsupported file format. Use .csv or .xlsx")
			continue
		
		return path


def map_columns(df, data_dir: Path, auto_mapping: dict, missing: List[str]) -> dict:
	"""Map metadata columns interactively if needed."""
	print_step(4, "Column Mapping")
	
	mapping = auto_mapping.copy()
	
	if not missing:
		console.print("[green]✓[/green] All required columns found automatically:")
		for standard, actual in mapping.items():
			if standard in REQUIRED_COLUMNS:
				console.print(f"  • [bold]{standard}[/bold] → {actual}")
		return mapping
	
	console.print(f"[yellow]![/yellow] Missing required columns: {', '.join(missing)}")
	console.print()
	
	# Interactive mapping for missing columns
	# Track already mapped columns to exclude them from suggestions
	mapped_cols = set(mapping.values())
	
	for col in missing:
		# Get suggestions, excluding already mapped columns
		all_suggestions = suggest_column_matches(df, col)
		suggestions = [s for s in all_suggestions if s not in mapped_cols]
		
		if not suggestions:
			console.print(f"[yellow]![/yellow] No unmapped columns available for '{col}'")
			continue
		
		console.print(f"[bold]Map column for '{col}':[/bold]")
		for i, suggestion in enumerate(suggestions, 1):
			# Show sample values
			sample = df[suggestion].dropna().head(2).tolist()
			sample_str = ", ".join(str(s)[:30] for s in sample)
			console.print(f"  {i}. {suggestion} [dim](e.g., {sample_str})[/dim]")
		console.print(f"  0. [skip]")
		
		while True:
			choice = Prompt.ask("Select", default="1")
			try:
				choice_int = int(choice)
				if choice_int == 0:
					console.print(f"[yellow]![/yellow] Skipping {col} - upload may fail")
					break
				if 1 <= choice_int <= len(suggestions):
					selected_col = suggestions[choice_int - 1]
					mapping[col] = selected_col
					mapped_cols.add(selected_col)  # Track as mapped
					console.print(f"[green]✓[/green] Mapped {col} → {mapping[col]}")
					break
			except ValueError:
				pass
			console.print("[red]Invalid choice[/red]")
	
	return mapping


def check_existing_session(data_dir: Path) -> Optional[UploadSessionState]:
	"""Check for existing upload session and offer to resume."""
	session = find_existing_session(data_dir)
	
	if session and not session.is_complete:
		console.print()
		console.print(Panel.fit(
			f"[yellow]Found incomplete upload session[/yellow]\n"
			f"Started: {session.created_at}\n"
			f"Completed: {len(session.files_completed)}/{session.files_total}\n"
			f"Failed: {len(session.files_failed)}",
			title="Previous Session",
			border_style="yellow",
		))
		
		if Confirm.ask("Resume previous session?"):
			return session
		
		if Confirm.ask("Start fresh (discard previous session)?"):
			session_file = get_session_file_path(data_dir)
			session_file.unlink(missing_ok=True)
			return None
		
		raise typer.Exit(0)
	
	return None


def confirm_upload(file_count: int, total_size_str: str) -> bool:
	"""Confirm upload with user."""
	console.print(f"Ready to upload [bold]{file_count}[/bold] files ({total_size_str})")
	return Confirm.ask("Continue?")
