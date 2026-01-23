"""Display and output formatting utilities."""

from typing import List

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from . import __version__
from .models import ValidationResult, UploadResult
from .upload import format_size


console = Console()


def print_header():
	"""Print welcome header."""
	console.print()
	console.print(Panel.fit(
		"[bold blue]DeadTrees Batch Upload CLI[/bold blue]\n"
		f"[dim]Version {__version__}[/dim]",
		border_style="blue",
	))
	console.print()


def print_step(number: int, title: str):
	"""Print step header."""
	console.print()
	console.rule(f"[bold]Step {number}: {title}[/bold]", style="cyan")
	console.print()


def show_validation_table(validation_results: List[ValidationResult]) -> tuple[int, int, int]:
	"""
	Display validation results in a table.
	
	Returns:
		Tuple of (valid_count, warning_count, error_count)
	"""
	table = Table(title="Validation Summary")
	table.add_column("File", style="cyan", no_wrap=True, max_width=40)
	table.add_column("Size", justify="right")
	table.add_column("Status", justify="center")
	table.add_column("Issues", style="dim")
	
	valid_count = 0
	warning_count = 0
	error_count = 0
	
	for result in validation_results:
		# Get file size
		if result.metadata and result.metadata.file_path:
			size = format_size(result.metadata.file_path.stat().st_size)
		else:
			size = "?"
		
		if result.errors:
			status = "[red]✗ Error[/red]"
			issues = "; ".join(result.errors[:2])
			error_count += 1
		elif result.warnings:
			status = "[yellow]⚠ Warn[/yellow]"
			issues = "; ".join(result.warnings[:2])
			warning_count += 1
			valid_count += 1  # Warnings are still valid
		else:
			status = "[green]✓ Valid[/green]"
			issues = ""
			valid_count += 1
		
		table.add_row(result.filename[:40], size, status, issues[:50])
	
	console.print(table)
	console.print()
	console.print(f"Summary: [green]{valid_count} valid[/green], [yellow]{warning_count} warnings[/yellow], [red]{error_count} errors[/red]")
	
	return valid_count, warning_count, error_count


def show_summary(upload_results: List[UploadResult], api_url: str):
	"""Show final upload summary."""
	console.print()
	console.rule("[bold]Upload Complete[/bold]", style="green")
	console.print()
	
	success_count = sum(1 for r in upload_results if r.success)
	failed_count = len(upload_results) - success_count
	
	console.print(f"[green]✓ Successful:[/green] {success_count}")
	if failed_count:
		console.print(f"[red]✗ Failed:[/red] {failed_count}")
	
	# Show failed uploads
	failed = [r for r in upload_results if not r.success]
	if failed:
		console.print()
		console.print("[bold]Failed uploads:[/bold]")
		for result in failed:
			console.print(f"  • {result.filename}: {result.error}")
	
	console.print()
	console.print("[bold]View your datasets at:[/bold]")
	console.print("  https://deadtrees.earth/account")
	console.print()


def show_parse_errors(parse_errors: List[tuple], max_show: int = 5):
	"""Show metadata parse errors."""
	if parse_errors:
		console.print(f"[yellow]![/yellow] {len(parse_errors)} rows with errors:")
		for row_num, error in parse_errors[:max_show]:
			console.print(f"  • Row {row_num}: {error}")
		if len(parse_errors) > max_show:
			console.print(f"  ... and {len(parse_errors) - max_show} more")
		console.print()


def show_unmatched_files(unmatched_files: List[str], max_show: int = 5):
	"""Show files without metadata."""
	if unmatched_files:
		console.print(f"[yellow]![/yellow] {len(unmatched_files)} files without metadata:")
		for filename in unmatched_files[:max_show]:
			console.print(f"  • {filename}")
		if len(unmatched_files) > max_show:
			console.print(f"  ... and {len(unmatched_files) - max_show} more")
		console.print()


def show_unmatched_metadata(unmatched_metadata: List[str], max_show: int = 5):
	"""Show metadata entries without files."""
	if unmatched_metadata:
		console.print(f"[yellow]![/yellow] {len(unmatched_metadata)} metadata entries without files:")
		for filename in unmatched_metadata[:max_show]:
			console.print(f"  • {filename}")
		if len(unmatched_metadata) > max_show:
			console.print(f"  ... and {len(unmatched_metadata) - max_show} more")
		console.print()


def show_duplicates(duplicates: List[tuple], max_show: int = 3):
	"""Show duplicate files found in batch."""
	if duplicates:
		console.print(f"[yellow]![/yellow] Found {len(duplicates)} duplicate files (same content):")
		for dup, orig in duplicates[:max_show]:
			console.print(f"  • {dup} = {orig}")
		if len(duplicates) > max_show:
			console.print(f"  ... and {len(duplicates) - max_show} more")
