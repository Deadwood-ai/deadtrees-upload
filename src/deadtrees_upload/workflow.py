"""Workflow logic for validation and upload."""

from pathlib import Path
from typing import Optional, List

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn

from .models import FileMetadata, ValidationResult, UploadResult
from .auth import AuthSession
from .metadata import parse_metadata
from .validation import find_uploadable_files, match_files_to_metadata, validate_all
from .upload import upload_file, format_size, trigger_processing
from .dedup import UploadSessionState, get_session_file_path, get_file_identifier
from .display import (
	print_step,
	show_validation_table,
	show_parse_errors,
	show_unmatched_files,
	show_unmatched_metadata,
	show_duplicates,
)
from .prompts import confirm_upload


console = Console()


def validate_and_match(
	data_dir: Path,
	metadata_path: Path,
	column_mapping: dict,
	df,
) -> List[ValidationResult]:
	"""Parse metadata, match files, and validate."""
	print_step(5, "Validation")
	
	# Parse metadata
	with console.status("[bold green]Parsing metadata...[/bold green]"):
		metadata_list, parse_errors = parse_metadata(df, column_mapping)
	
	show_parse_errors(parse_errors)
	
	if not metadata_list:
		console.print("[red]✗[/red] No valid metadata entries found")
		raise typer.Exit(1)
	
	# Find files in directory
	files, _ = find_uploadable_files(data_dir)
	
	# Match files to metadata
	matched, unmatched_files, unmatched_metadata = match_files_to_metadata(files, metadata_list)
	
	show_unmatched_files(unmatched_files)
	show_unmatched_metadata(unmatched_metadata)
	
	if not matched:
		console.print("[red]✗[/red] No files matched to metadata")
		raise typer.Exit(1)
	
	console.print(f"[green]✓[/green] Matched {len(matched)} files to metadata")
	console.print()
	
	# Validate files
	with console.status("[bold green]Validating files...[/bold green]"):
		validation_results = validate_all(matched)
	
	# Show validation summary table
	show_validation_table(validation_results)
	
	return validation_results


def calculate_hashes_with_progress(
	validation_results: List[ValidationResult],
	session: UploadSessionState,
) -> None:
	"""Calculate file hashes and update session state."""
	console.print()
	console.print("[bold]Calculating file hashes for duplicate detection...[/bold]")
	
	with Progress(
		SpinnerColumn(),
		TextColumn("[progress.description]{task.description}"),
		BarColumn(),
		TaskProgressColumn(),
		console=console,
	) as progress:
		task = progress.add_task("Hashing files", total=len(validation_results))
		
		for result in validation_results:
			if result.metadata and result.metadata.file_path:
				filename = result.metadata.filename
				if filename not in session.file_hashes:
					try:
						file_hash = get_file_identifier(result.metadata.file_path)
						session.file_hashes[filename] = file_hash
					except Exception as e:
						console.print(f"[yellow]![/yellow] Could not hash {filename}: {e}")
			progress.advance(task)
	
	console.print(f"[green]✓[/green] Calculated {len(session.file_hashes)} file hashes")


def do_upload(
	validation_results: List[ValidationResult],
	token: AuthSession,
	api_url: str,
	dry_run: bool,
	session: Optional[UploadSessionState] = None,
	data_dir: Optional[Path] = None,
) -> List[UploadResult]:
	"""Upload all valid files with session state tracking."""
	print_step(6, "Upload")
	
	# Filter to valid files only
	valid_results = [r for r in validation_results if r.is_valid and r.metadata]
	
	if not valid_results:
		console.print("[red]✗[/red] No valid files to upload")
		raise typer.Exit(1)
	
	# Initialize or update session
	if session is None and data_dir:
		session = UploadSessionState.create(
			data_directory=str(data_dir),
			metadata_file="",
			api_url=api_url,
		)
	
	if session:
		session.files_total = len(valid_results)
		
		# Calculate hashes for duplicate detection
		calculate_hashes_with_progress(valid_results, session)
		
		# Check for already-completed files (from previous session)
		already_done = [r for r in valid_results if r.metadata.filename in session.files_completed]
		if already_done:
			console.print(f"[dim]Skipping {len(already_done)} already-uploaded files[/dim]")
			valid_results = [r for r in valid_results if r.metadata.filename not in session.files_completed]
		
		# Check for local duplicates (same hash in this batch)
		seen_hashes = {}
		duplicates = []
		for result in valid_results:
			filename = result.metadata.filename
			file_hash = session.file_hashes.get(filename)
			if file_hash:
				if file_hash in seen_hashes:
					duplicates.append((filename, seen_hashes[file_hash]))
					session.mark_skipped(filename, f"Duplicate of {seen_hashes[file_hash]}")
				else:
					seen_hashes[file_hash] = filename
		
		show_duplicates(duplicates)
		if duplicates:
			valid_results = [r for r in valid_results if r.metadata.filename not in session.files_skipped]
	
	if not valid_results:
		console.print("[green]✓[/green] All files already uploaded or skipped")
		return []
	
	if dry_run:
		console.print("[yellow]DRY RUN[/yellow] - No files will be uploaded")
		console.print(f"Would upload {len(valid_results)} files:")
		for result in valid_results:
			console.print(f"  • {result.filename}")
		return []
	
	# Confirm upload
	total_size = sum(
		r.metadata.file_path.stat().st_size
		for r in valid_results
		if r.metadata and r.metadata.file_path
	)
	
	if not confirm_upload(len(valid_results), format_size(total_size)):
		raise typer.Exit(0)
	
	console.print()
	
	# Upload files sequentially with progress
	upload_results = []
	
	with Progress(
		SpinnerColumn(),
		TextColumn("[progress.description]{task.description}"),
		BarColumn(),
		TaskProgressColumn(),
		TimeRemainingColumn(),
		console=console,
	) as progress:
		# Overall progress
		overall_task = progress.add_task(
			f"[bold]Uploading {len(valid_results)} files...[/bold]",
			total=len(valid_results),
		)
		
		for result in valid_results:
			metadata = result.metadata
			file_size = metadata.file_path.stat().st_size if metadata.file_path else 0
			
			# File-specific progress
			file_task = progress.add_task(
				f"  {metadata.filename[:30]}...",
				total=file_size,
			)
			
			# Upload with token refresh support
			upload_result = upload_file(
				metadata=metadata,
				token=token,  # AuthSession handles refresh
				api_url=api_url,
				progress=progress,
				task_id=file_task,
			)
			
			upload_results.append(upload_result)
			
			# Update session state
			if session:
				if upload_result.success:
					session.mark_completed(metadata.filename, upload_result.dataset_id)
				else:
					session.mark_failed(metadata.filename, upload_result.error or "Unknown error")
				
				# Save session after each file (for resume on crash)
				if data_dir:
					try:
						session.save(get_session_file_path(data_dir))
					except Exception:
						pass  # Don't fail upload if session save fails
			
			# Update overall progress
			progress.update(overall_task, advance=1)
			
			# Mark file task complete
			progress.update(file_task, completed=file_size)
			
			# Log result and trigger processing
			if upload_result.success:
				# Trigger processing pipeline
				processing_ok = trigger_processing(
					dataset_id=upload_result.dataset_id,
					upload_type=metadata.upload_type,
					token=token,
					api_url=api_url,
				)
				
				if processing_ok:
					progress.console.print(
						f"  [green]✓[/green] {metadata.filename} → Dataset ID: {upload_result.dataset_id} [dim](processing started)[/dim]"
					)
				else:
					progress.console.print(
						f"  [yellow]⚠[/yellow] {metadata.filename} → Dataset ID: {upload_result.dataset_id} [dim](upload ok, processing failed to start)[/dim]"
					)
			else:
				progress.console.print(
					f"  [red]✗[/red] {metadata.filename}: {upload_result.error}"
				)
	
	return upload_results
