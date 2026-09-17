"""Main CLI entry point using Typer."""

import sys
import json
import httpx
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Prompt

from . import __version__
from .config import DEFAULT_API_URL
from .auth import create_auth_session, AuthError, save_auth_session
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
    non_interactive: bool = typer.Option(False, "--non-interactive", help="Never prompt; require explicit metadata and credentials"),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON result to stdout (implies non-interactive)"),
    yes: bool = typer.Option(False, "--yes", help="Confirm the authorized upload without prompting"),
    resume: bool = typer.Option(False, "--resume", help="Reuse the agent receipt; never retry unresolved uploads"),
    process: bool = typer.Option(False, "--process", help="Also request platform processing after upload"),
	dry_run: bool = typer.Option(
		False,
		"--dry-run",
		help="Validate without uploading",
	),
):
	"""
	Batch upload RGB forest imagery to deadtrees.earth.
	
	Use --dry-run --json for offline validation; --non-interactive --yes for authorized upload.
	Run without arguments in a terminal for the human wizard.
	
	Features:
	- Auto-refresh tokens for long uploads
	- Resume interrupted uploads
	- Local duplicate detection
	- Session state saved to .deadtrees-upload-session.json
	"""
	# If a subcommand was invoked, skip main logic
	if ctx.invoked_subcommand is not None:
		return
	
	if non_interactive or json_output or dry_run or yes or resume or process or not sys.stdin.isatty():
		from . import batch
		from .config import validate_url
		try:
			if data_dir is None or metadata is None:
				raise batch.BatchError("Provide --data-dir and --metadata; use --help for unattended usage")
			data_dir, metadata = data_dir.expanduser().resolve(), metadata.expanduser().resolve()
			report = batch.plan(data_dir, metadata)
			code = 0 if report["success"] else 2
			if report["success"] and not dry_run:
				if not yes:
					raise batch.BatchError("Upload requires --yes after user authorization; use --dry-run for offline validation")
				validate_url(api_url)
				token = batch.authenticate(api_url, email)
				warnings = {item["filename"]: item["warnings"] for item in report["files"] if item["warnings"]}
				report = batch.submit(report, data_dir, metadata, api_url, token, resume, process)
				report["warnings"] = warnings
				code = report.pop("exit_code")
		except batch.BatchError as e:
			report, code = {"schema_version": 1, "success": False, "errors": [str(e)]}, e.code
		except AuthError:
			report, code = {"schema_version": 1, "success": False, "errors": ["Authentication failed; check credentials and selected endpoint"]}, 3
		except httpx.HTTPError:
			report, code = {"schema_version": 1, "success": False, "errors": ["Network request failed; inspect any existing receipt before retrying"]}, 4
		except (MetadataError, ValidationError, ValueError, OSError) as e:
			report, code = {"schema_version": 1, "success": False, "errors": [str(e)]}, 2
		_emit(report, json_output)
		raise typer.Exit(code)

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
				try:
					save_auth_session(auth_session, api_url)
				except Exception:
					console.print("[yellow]![/yellow] Could not persist credentials")
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
	
	# Step 3-5: Metadata file, column mapping, and validation (with retry support)
	validation_results = None
	metadata_path = metadata.expanduser().resolve() if metadata else None
	
	while validation_results is None:
		# Step 3: Metadata file
		if metadata_path is None:
			metadata_path = select_metadata_file(data_dir)
		else:
			print_step(3, "Metadata File")
			console.print(f"Using metadata file: {metadata_path}")
		
		# Read metadata file
		try:
			df = read_metadata_file(metadata_path)
			console.print(f"[green]✓[/green] Loaded {len(df)} rows from metadata file")
		except MetadataError as e:
			console.print(f"[red]✗[/red] Metadata error: {e}")
			if Prompt.ask(
				"\nWould you like to edit the file and retry?",
				choices=["y", "n"],
				default="y"
			) == "y":
				console.print("\n[dim]Fix the metadata file and press Enter when ready...[/dim]")
				Prompt.ask("Press Enter to continue")
				metadata_path = None  # Re-prompt for file
				continue
			else:
				raise typer.Exit(1)
		
		# Step 4: Column mapping
		auto_mapping, missing = find_column_mapping(df)
		column_mapping = map_columns(df, data_dir, auto_mapping, missing)
		
		# Step 5: Validation
		try:
			validation_results = validate_and_match(data_dir, metadata_path, column_mapping, df)
		except typer.Exit:
			# Validation failed - offer retry
			console.print("\n[yellow]Validation failed.[/yellow]")
			if Prompt.ask(
				"Would you like to fix the metadata and retry?",
				choices=["y", "n"],
				default="y"
			) == "y":
				console.print("\n[dim]Fix the metadata file and press Enter when ready...[/dim]")
				Prompt.ask("Press Enter to continue")
				metadata_path = None  # Re-prompt for file
				validation_results = None  # Reset to retry
				continue
			else:
				raise typer.Exit(1)
	
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
		if not all(r.success for r in upload_results):
			raise typer.Exit(4)


def _emit(report, json_output):
    if json_output:
        typer.echo(json.dumps(report))
    else:
        console.print_json(data=report)


@app.command()
def login(api_url: str = typer.Option(DEFAULT_API_URL, "--api-url")):
    """Human-only terminal login: save a refreshable session without uploading."""
    if not sys.stdin.isatty():
        typer.echo("Login requires a human terminal. Do not send passwords in chat; unattended commands can reuse a saved session.", err=True)
        raise typer.Exit(3)
    try:
        supabase_url, supabase_key = get_supabase_config(api_url)
        email = Prompt.ask("Email")
        password = Prompt.ask("Password", password=True)
        session = create_auth_session(email, password, supabase_url, supabase_key)
        save_auth_session(session, api_url)
    except AuthError:
        typer.echo("Login failed. Check your account and selected endpoint; no upload was attempted.", err=True)
        raise typer.Exit(3)
    except (OSError, ValueError):
        typer.echo("Session could not be saved or endpoint configuration is invalid. Check local cache access and configuration; no upload was attempted.", err=True)
        raise typer.Exit(3)
    typer.echo("Session saved for this API target. Agents running as this OS user can reuse it; no upload or processing was requested.")


@app.command()
def status(
    dataset_id: int = typer.Argument(..., min=1),
    api_url: str = typer.Option(DEFAULT_API_URL, "--api-url"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Read one dataset's processing flags; no upload or processing request."""
    from . import batch
    try:
        report, code = batch.status(dataset_id, api_url), 0
    except batch.BatchError as e:
        report, code = {"success": False, "errors": [str(e)]}, e.code
    except AuthError:
        report, code = {"success": False, "errors": ["Authentication failed"]}, 3
    except Exception:
        report, code = {"success": False, "errors": ["Status unavailable; check endpoint and authentication configuration"]}, 4
    _emit(report, json_output)
    raise typer.Exit(code)


@app.command()
def version():
	"""Show version information."""
	console.print(f"deadtrees-upload version {__version__}")


if __name__ == "__main__":
	app()
