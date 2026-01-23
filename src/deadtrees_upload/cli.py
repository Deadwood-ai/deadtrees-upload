"""Main CLI entry point using Typer."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Prompt

from . import __version__
from .auth import create_auth_session, AuthError
from .metadata import read_metadata_file, find_column_mapping, MetadataError
from .validation import find_uploadable_files, ValidationError
from .dedup import get_session_file_path
from .display import print_header, print_step, show_summary
from .prompts import (
	get_supabase_config,
	authenticate,
	select_data_directory,
	select_metadata_file,
	map_columns,
	check_existing_session,
)
from .workflow import validate_and_match, do_upload


# Create Typer app
app = typer.Typer(
	name="deadtrees-upload",
	help="Batch upload datasets to deadtrees.earth",
	add_completion=False,
	invoke_without_command=True,
)

console = Console()

# Default values
DEFAULT_API_URL = "https://data2.deadtrees.earth/api/v1/"


@app.callback(invoke_without_command=True)
def main(
	ctx: typer.Context,
	data_dir: Optional[Path] = typer.Option(
		None,
		"--data-dir", "-d",
		help="Path to directory containing files to upload",
	),
	metadata: Optional[Path] = typer.Option(
		None,
		"--metadata", "-m",
		help="Path to metadata CSV/Excel file",
	),
	email: Optional[str] = typer.Option(
		None,
		"--email", "-e",
		help="Email for authentication",
	),
	api_url: str = typer.Option(
		DEFAULT_API_URL,
		"--api-url",
		help="API URL (for development/testing)",
	),
	dry_run: bool = typer.Option(
		False,
		"--dry-run",
		help="Validate without uploading",
	),
):
	"""
	Batch upload datasets to deadtrees.earth.
	
	Run without arguments for interactive mode, or provide all options for non-interactive mode.
	
	Features:
	- Auto-refresh tokens for long uploads
	- Resume interrupted uploads
	- Local duplicate detection
	- Session state saved to .deadtrees-upload-session.json
	"""
	# If a subcommand was invoked, skip main logic
	if ctx.invoked_subcommand is not None:
		return
	
	print_header()
	
	# Step 1: Authentication
	supabase_url, supabase_key = get_supabase_config(api_url)
	
	if email:
		print_step(1, "Authentication")
		if "localhost" in api_url:
			console.print("[dim]Using local Supabase for authentication[/dim]")
		password = Prompt.ask("[bold]Password[/bold]", password=True)
		with console.status("[bold green]Authenticating...[/bold green]"):
			try:
				auth_session = create_auth_session(
					email=email,
					password=password,
					supabase_url=supabase_url,
					supabase_key=supabase_key,
				)
				console.print(f"[green]✓[/green] Authenticated as [bold]{email}[/bold]")
				console.print("[dim]Token will auto-refresh during long uploads[/dim]")
			except AuthError as e:
				console.print(f"[red]✗[/red] Authentication failed: {e}")
				raise typer.Exit(1)
	else:
		auth_session = authenticate(api_url)
	
	# Step 2: Data directory
	if data_dir is None:
		data_dir = select_data_directory()
	else:
		data_dir = data_dir.expanduser().resolve()
		print_step(2, "Select Data Directory")
		try:
			files, file_types = find_uploadable_files(data_dir)
			geotiff_count = sum(1 for t in file_types.values() if t == "GeoTIFF")
			zip_count = sum(1 for t in file_types.values() if t == "ZIP")
			console.print(f"[green]✓[/green] Found [bold]{len(files)}[/bold] files")
			if geotiff_count:
				console.print(f"  • {geotiff_count} GeoTIFF files")
			if zip_count:
				console.print(f"  • {zip_count} ZIP files")
		except ValidationError as e:
			console.print(f"[red]✗[/red] {e}")
			raise typer.Exit(1)
	
	# Check for existing upload session (resume support)
	upload_session = check_existing_session(data_dir)
	
	# Step 3: Metadata file
	if metadata is None:
		metadata_path = select_metadata_file(data_dir)
	else:
		metadata_path = metadata.expanduser().resolve()
		print_step(3, "Metadata File")
		console.print(f"Using metadata file: {metadata_path}")
	
	# Read metadata file
	try:
		df = read_metadata_file(metadata_path)
		console.print(f"[green]✓[/green] Loaded {len(df)} rows from metadata file")
	except MetadataError as e:
		console.print(f"[red]✗[/red] {e}")
		raise typer.Exit(1)
	
	# Step 4: Column mapping
	auto_mapping, missing = find_column_mapping(df)
	column_mapping = map_columns(df, data_dir, auto_mapping, missing)
	
	# Step 5: Validation
	validation_results = validate_and_match(data_dir, metadata_path, column_mapping, df)
	
	# Step 6: Upload with session tracking
	upload_results = do_upload(
		validation_results,
		auth_session,
		api_url,
		dry_run,
		session=upload_session,
		data_dir=data_dir,
	)
	
	# Clean up session file on successful completion
	if upload_results and all(r.success for r in upload_results):
		session_file = get_session_file_path(data_dir)
		session_file.unlink(missing_ok=True)
	
	# Summary
	if upload_results:
		show_summary(upload_results, api_url)


@app.command()
def version():
	"""Show version information."""
	console.print(f"deadtrees-upload version {__version__}")


if __name__ == "__main__":
	app()
