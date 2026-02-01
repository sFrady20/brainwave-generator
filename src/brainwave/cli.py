"""Command-line interface for brainwave."""

import sys
from pathlib import Path
from typing import Optional

import structlog
import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from brainwave import __version__
from brainwave.builder import EpisodeBuilder
from brainwave.config import load_config
from brainwave.exporter import UnityExporter, generate_preview_text
from brainwave.generator import EpisodeGenerator, EpisodeManager

# Set up console
console = Console()

# Create app
app = typer.Typer(
    name="brainwave",
    help="Automated episode generation for Unity-based 3D cartoon livestreaming",
    add_completion=False,
)


def get_root_dir() -> Path:
    """Get the project root directory."""
    # Start from current directory and look for pyproject.toml
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").exists():
            return parent
        if (parent / "config.yaml").exists():
            return parent
    return current


def setup_logging(debug: bool = False) -> None:
    """Configure structlog for CLI output."""
    import logging

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if debug else logging.INFO
        ),
    )


@app.callback()
def main(
    ctx: typer.Context,
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug mode"),
    config_path: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config file"
    ),
) -> None:
    """Brainwave - Episode Generator for Unity Cartoons."""
    setup_logging(debug)

    root_dir = get_root_dir()
    ctx.ensure_object(dict)
    ctx.obj["root_dir"] = root_dir
    ctx.obj["config"] = load_config(config_path, root_dir)
    ctx.obj["debug"] = debug


@app.command()
def generate(
    ctx: typer.Context,
    episode_id: Optional[str] = typer.Argument(None, help="Episode ID to generate script for (from preview)"),
    topic: Optional[str] = typer.Option(None, "--topic", "-t", help="Topic/premise for a new episode"),
) -> None:
    """Generate a complete episode with plot and script.

    If EPISODE_ID is provided, generates full script from existing preview.
    Otherwise, generates a new episode from scratch.
    """
    config = ctx.obj["config"]

    generator = EpisodeGenerator(config)
    manager = EpisodeManager(config.paths.scenes_dir)
    exporter = UnityExporter()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        try:
            if episode_id:
                # Generate from existing preview
                task = progress.add_task("Loading preview...", total=None)

                try:
                    episode = manager.load(episode_id)
                except FileNotFoundError:
                    console.print(f"[red]Episode not found: {episode_id}[/red]")
                    raise typer.Exit(1)

                if not episode.plot:
                    console.print(f"[red]Episode has no plot. Generate a preview first.[/red]")
                    raise typer.Exit(1)

                progress.update(task, description=f"Generating script for '{episode.plot.title}'...")
                episode = generator.generate_from_plot(episode)

            else:
                # Generate new episode from scratch
                task = progress.add_task("Generating episode...", total=None)
                episode = generator.generate(topic=topic)

            progress.update(task, description="Saving episode...")
            episode_dir = manager.save(episode)

            progress.update(task, description="Exporting Unity manifest...")
            exporter.export(episode, episode_dir)

        except typer.Exit:
            raise
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            if ctx.obj.get("debug"):
                raise
            raise typer.Exit(1)

    # Show results
    console.print()
    console.print(Panel(
        f"[green]Episode generated successfully![/green]\n\n"
        f"[bold]ID:[/bold] {episode.id_str}\n"
        f"[bold]Title:[/bold] {episode.meta.title}\n"
        f"[bold]Scenes:[/bold] {episode.meta.scene_count}\n"
        f"[bold]Dialog lines:[/bold] {episode.meta.dialog_count}\n"
        f"[bold]Location:[/bold] {episode_dir}",
        title="Episode Created",
    ))


@app.command()
def preview(
    ctx: typer.Context,
    topic: Optional[str] = typer.Option(None, "--topic", "-t", help="Topic/premise for the episode"),
) -> None:
    """Generate a plot-only preview (no full script)."""
    config = ctx.obj["config"]

    generator = EpisodeGenerator(config)
    manager = EpisodeManager(config.paths.scenes_dir)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Generating plot preview...", total=None)

        try:
            episode = generator.generate_preview(topic=topic)

            progress.update(task, description="Saving preview...")
            episode_dir = manager.save(episode)

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)

    # Show results
    console.print()
    console.print(Panel(
        f"[green]Preview generated![/green]\n\n"
        f"[bold]ID:[/bold] {episode.id_str}\n"
        f"[bold]Title:[/bold] {episode.plot.title if episode.plot else 'Untitled'}\n"
        f"[bold]Location:[/bold] {episode_dir}\n\n"
        f"[dim]Run 'brainwave generate {episode.id_str}' to generate full script[/dim]",
        title="Plot Preview",
    ))

    # Show plot
    if episode.plot:
        console.print()
        for beat in episode.plot.beats:
            beat_name = beat.name.replace("_", " ").title()
            console.print(f"[bold]{beat_name}:[/bold]")
            console.print(f"  {beat.content[:200]}..." if len(beat.content) > 200 else f"  {beat.content}")
            console.print()


@app.command()
def build(
    ctx: typer.Context,
    episode_id: str = typer.Argument(..., help="Episode ID to build"),
    mock: bool = typer.Option(False, "--mock", "-m", help="Use mock TTS (no API calls)"),
    force: bool = typer.Option(False, "--force", "-f", help="Regenerate existing audio files"),
) -> None:
    """Generate TTS audio for an episode's dialog."""
    config = ctx.obj["config"]

    # Override TTS provider if mock
    if mock:
        config.tts.provider = "mock"

    manager = EpisodeManager(config.paths.scenes_dir)
    builder = EpisodeBuilder(config)

    try:
        console.print(f"Loading episode {episode_id}...")
        episode = manager.load(episode_id)

    except FileNotFoundError:
        console.print(f"[red]Episode not found: {episode_id}[/red]")
        raise typer.Exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Building audio assets...", total=None)

        try:
            results = builder.build(episode, force=force)

            progress.update(task, description="Saving metadata...")
            manager.save(episode)

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)

    # Count results
    success = sum(1 for r in results if r.success)
    cached = sum(1 for r in results if r.cached)
    failed = sum(1 for r in results if not r.success and not r.cached)

    console.print()
    console.print(Panel(
        f"[green]Build complete![/green]\n\n"
        f"[bold]Generated:[/bold] {success - cached}\n"
        f"[bold]Cached:[/bold] {cached}\n"
        f"[bold]Failed:[/bold] {failed}\n"
        f"[bold]TTS Provider:[/bold] {config.tts.provider}",
        title="Build Results",
    ))


@app.command()
def batch(
    ctx: typer.Context,
    count: int = typer.Option(1, "--count", "-n", help="Number of episodes to generate"),
    topics_file: Optional[Path] = typer.Option(None, "--topics", help="File with topics (one per line)"),
) -> None:
    """Generate multiple episodes in batch."""
    config = ctx.obj["config"]

    generator = EpisodeGenerator(config)
    manager = EpisodeManager(config.paths.scenes_dir)
    exporter = UnityExporter()

    # Load topics from file if provided
    topics: list[str | None] = [None] * count
    if topics_file and topics_file.exists():
        with open(topics_file) as f:
            file_topics = [line.strip() for line in f if line.strip()]
        topics = file_topics[:count]
        if len(topics) < count:
            topics.extend([None] * (count - len(topics)))

    results_table = Table(title="Batch Generation Results")
    results_table.add_column("Episode ID", style="cyan")
    results_table.add_column("Title")
    results_table.add_column("Scenes", justify="right")
    results_table.add_column("Status")

    console.print(f"\nGenerating {count} episode(s)...\n")

    success_count = 0
    for i in range(count):
        topic = topics[i] if i < len(topics) else None

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(f"Episode {i + 1}/{count}...", total=None)

            try:
                episode = generator.generate(topic=topic)
                episode_dir = manager.save(episode)
                exporter.export(episode, episode_dir)

                results_table.add_row(
                    episode.id_str[:8] + "...",
                    episode.meta.title or "Untitled",
                    str(episode.meta.scene_count),
                    "[green]Success[/green]",
                )
                success_count += 1

            except Exception as e:
                results_table.add_row(
                    "N/A",
                    topic[:30] + "..." if topic and len(topic) > 30 else (topic or "Random"),
                    "-",
                    f"[red]Failed: {str(e)[:20]}[/red]",
                )

    console.print(results_table)
    console.print(f"\n[bold]Completed:[/bold] {success_count}/{count} episodes")


@app.command("export")
def export_manifest(
    ctx: typer.Context,
    episode_id: str = typer.Argument(..., help="Episode ID to export"),
) -> None:
    """Export Unity JSON manifest for an episode."""
    config = ctx.obj["config"]

    manager = EpisodeManager(config.paths.scenes_dir)
    exporter = UnityExporter()

    try:
        console.print(f"Loading episode {episode_id}...")
        episode = manager.load(episode_id)

    except FileNotFoundError:
        console.print(f"[red]Episode not found: {episode_id}[/red]")
        raise typer.Exit(1)

    manifest_path = exporter.export(episode)
    dialogs_path = exporter.export_dialog_list(episode)

    console.print()
    console.print(Panel(
        f"[green]Export complete![/green]\n\n"
        f"[bold]Manifest:[/bold] {manifest_path}\n"
        f"[bold]Dialogs:[/bold] {dialogs_path}",
        title="Export Results",
    ))


@app.command("list")
def list_episodes(ctx: typer.Context) -> None:
    """List all generated episodes."""
    config = ctx.obj["config"]

    manager = EpisodeManager(config.paths.scenes_dir)
    episode_ids = manager.list_episodes()

    if not episode_ids:
        console.print("[yellow]No episodes found.[/yellow]")
        return

    table = Table(title="Episodes")
    table.add_column("ID", style="cyan")
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Scenes", justify="right")
    table.add_column("Created")

    for episode_id in episode_ids[-20:]:  # Show last 20
        try:
            episode = manager.load(episode_id)
            table.add_row(
                episode_id[:8] + "...",
                episode.meta.title or "Untitled",
                episode.meta.status.value,
                str(episode.meta.scene_count or "-"),
                episode.meta.created_at.strftime("%Y-%m-%d %H:%M") if episode.meta.created_at else "-",
            )
        except Exception:
            table.add_row(episode_id[:8] + "...", "[red]Error loading[/red]", "-", "-", "-")

    console.print(table)


@app.command()
def show(
    ctx: typer.Context,
    episode_id: str = typer.Argument(..., help="Episode ID to show"),
) -> None:
    """Show details of an episode."""
    config = ctx.obj["config"]

    manager = EpisodeManager(config.paths.scenes_dir)

    try:
        episode = manager.load(episode_id)

    except FileNotFoundError:
        console.print(f"[red]Episode not found: {episode_id}[/red]")
        raise typer.Exit(1)

    preview = generate_preview_text(episode)
    console.print(preview)


@app.command()
def version() -> None:
    """Show version information."""
    console.print(f"brainwave version {__version__}")


if __name__ == "__main__":
    app()
