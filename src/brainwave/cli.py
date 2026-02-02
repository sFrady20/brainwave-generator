"""Command-line interface for brainwave."""

import sys
from pathlib import Path
from typing import Optional

import structlog
import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm
from rich.table import Table

from brainwave import __version__
from brainwave.builder import EpisodeBuilder
from brainwave.config import load_config
from brainwave.exporter import UnityExporter, generate_preview_text
from brainwave.generator import EpisodeGenerator, EpisodeManager
from brainwave.models.episode import Episode, EpisodeStatus, PipelineStep
from brainwave.pipeline import EpisodePipeline

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


def make_confirm_callback(auto_yes: bool):
    """Create a confirmation callback for the pipeline."""
    def confirm_callback(episode: Episode, step: PipelineStep) -> bool:
        if auto_yes:
            return True

        step_names = {
            PipelineStep.OUTLINE: "Outline",
            PipelineStep.SCRIPT: "Script",
            PipelineStep.BUILD: "Build",
        }

        console.print()
        console.print(Panel(
            f"[bold]Step completed:[/bold] {step_names.get(step, step.value)}\n"
            f"[bold]Episode:[/bold] {episode.title}\n"
            f"[bold]Status:[/bold] {episode.meta.status.value}",
            title=f"{step_names.get(step, step.value)} Complete",
        ))

        next_step = episode.meta.get_next_step()
        if next_step:
            return Confirm.ask(f"Continue to {next_step.value} step?", default=True)
        return True

    return confirm_callback


def make_build_callback(config, force: bool = False, silent: bool = False):
    """Create a build callback for the pipeline."""
    builder = EpisodeBuilder(config)

    def build_callback(episode: Episode) -> Episode:
        if silent:
            builder.build(episode, force=force)
        else:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Building audio assets...", total=None)
                builder.build(episode, force=force)
        return episode

    return build_callback


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


# ============================================================================
# NEW PIPELINE COMMANDS
# ============================================================================


@app.command()
def new(
    ctx: typer.Context,
    topic: Optional[str] = typer.Option(None, "--topic", "-t", help="Topic/premise for the episode"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip all confirmations"),
    mock: bool = typer.Option(False, "--mock", "-m", help="Use mock TTS (no API calls)"),
) -> None:
    """Start a new episode pipeline.

    Creates a new episode and runs through: Outline → Script → Build → Complete.
    At each step, you can review the output and choose to continue or pause.

    Use --yes to skip confirmations and run the full pipeline automatically.
    """
    config = ctx.obj["config"]

    if mock:
        config.tts.provider = "mock"

    pipeline = EpisodePipeline(config)

    console.print(f"\n[bold]Starting new episode...[/bold]")
    if topic:
        console.print(f"[dim]Topic: {topic}[/dim]")

    try:
        # Create episode first
        episode = pipeline.create(topic)
        console.print(f"[dim]Episode ID: {episode.id_str[:8]}...[/dim]\n")

        # Run each step with visible progress
        steps = [
            (PipelineStep.OUTLINE, "Generating outline", pipeline.run_outline),
            (PipelineStep.SCRIPT, "Generating script", pipeline.run_script),
            (PipelineStep.BUILD, "Building audio", lambda ep: pipeline.run_build(ep, make_build_callback(config, silent=True))),
            (PipelineStep.COMPLETE, "Uploading to storage", pipeline.run_complete),
        ]

        confirm_cb = make_confirm_callback(yes)

        for step, description, runner in steps:
            # Show spinner during generation
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task(f"{description}...", total=None)
                episode = runner(episode)

            # Confirm before next step (except after complete)
            if step != PipelineStep.COMPLETE:
                if not confirm_cb(episode, step):
                    console.print(f"\n[yellow]Paused after {step.value} step.[/yellow]")
                    _show_episode_status(episode)
                    return

    except KeyboardInterrupt:
        console.print(f"\n[yellow]Interrupted. Episode saved to .incomplete/[/yellow]")
        raise typer.Exit(0)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if ctx.obj.get("debug"):
            raise
        raise typer.Exit(1)

    # Show final status
    _show_episode_status(episode)


@app.command()
def resume(
    ctx: typer.Context,
    episode_id: Optional[str] = typer.Argument(None, help="Episode ID to resume"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip all confirmations"),
    mock: bool = typer.Option(False, "--mock", "-m", help="Use mock TTS (no API calls)"),
) -> None:
    """Resume a paused episode from its current step.

    If no episode ID is provided and there's only one incomplete episode,
    that one will be resumed automatically.
    """
    config = ctx.obj["config"]

    if mock:
        config.tts.provider = "mock"

    pipeline = EpisodePipeline(config)

    # If no episode ID, try to find one
    if not episode_id:
        incomplete = pipeline.list_incomplete()
        if len(incomplete) == 0:
            console.print("[yellow]No incomplete episodes found.[/yellow]")
            raise typer.Exit(0)
        elif len(incomplete) == 1:
            episode_id = incomplete[0][0]
            console.print(f"[dim]Resuming only incomplete episode: {episode_id[:8]}...[/dim]")
        else:
            console.print("[yellow]Multiple incomplete episodes found. Please specify one:[/yellow]")
            _list_incomplete_episodes(incomplete)
            raise typer.Exit(1)

    console.print(f"\n[bold]Resuming episode {episode_id[:8]}...[/bold]")

    try:
        confirm_cb = make_confirm_callback(yes)
        build_cb = make_build_callback(config)

        episode = pipeline.resume(
            episode_id,
            confirm_callback=confirm_cb,
            build_callback=build_cb,
        )

    except FileNotFoundError:
        console.print(f"[red]Episode not found: {episode_id}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if ctx.obj.get("debug"):
            raise
        raise typer.Exit(1)

    _show_episode_status(episode)


@app.command()
def outline(
    ctx: typer.Context,
    episode_id: str = typer.Argument(..., help="Episode ID to generate outline for"),
) -> None:
    """Re-run the outline step for an episode."""
    config = ctx.obj["config"]
    pipeline = EpisodePipeline(config)

    try:
        episode = pipeline.load(episode_id)
    except FileNotFoundError:
        console.print(f"[red]Episode not found: {episode_id}[/red]")
        raise typer.Exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Generating outline...", total=None)
        episode = pipeline.run_outline(episode)

    console.print()
    console.print(Panel(
        f"[green]Outline generated![/green]\n\n"
        f"[bold]Title:[/bold] {episode.title}\n"
        f"[bold]Premise:[/bold] {episode.outline.premise if episode.outline else 'N/A'}\n"
        f"[bold]Scenes:[/bold] {len(episode.outline.scenes) if episode.outline else 0}",
        title="Outline Complete",
    ))


@app.command()
def script(
    ctx: typer.Context,
    episode_id: str = typer.Argument(..., help="Episode ID to generate script for"),
) -> None:
    """Re-run the script step for an episode."""
    config = ctx.obj["config"]
    pipeline = EpisodePipeline(config)

    try:
        episode = pipeline.load(episode_id)
    except FileNotFoundError:
        console.print(f"[red]Episode not found: {episode_id}[/red]")
        raise typer.Exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Generating script...", total=None)
        episode = pipeline.run_script(episode)

    console.print()
    console.print(Panel(
        f"[green]Script generated![/green]\n\n"
        f"[bold]Scenes:[/bold] {episode.meta.scene_count}\n"
        f"[bold]Dialog lines:[/bold] {episode.meta.dialog_count}",
        title="Script Complete",
    ))


@app.command()
def complete(
    ctx: typer.Context,
    episode_id: str = typer.Argument(..., help="Episode ID to upload to cloud"),
) -> None:
    """Upload a built episode to cloud storage."""
    config = ctx.obj["config"]
    pipeline = EpisodePipeline(config)

    try:
        episode = pipeline.load(episode_id)
    except FileNotFoundError:
        console.print(f"[red]Episode not found: {episode_id}[/red]")
        raise typer.Exit(1)

    if episode.meta.status != EpisodeStatus.BUILT:
        console.print(f"[red]Episode must be built before completing. Current status: {episode.meta.status.value}[/red]")
        raise typer.Exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Uploading to cloud storage...", total=None)
        episode = pipeline.run_complete(episode)

    console.print()
    console.print(Panel(
        f"[green]Episode uploaded to cloud![/green]\n\n"
        f"[bold]Title:[/bold] {episode.title}\n"
        f"[bold]Storage:[/bold] {config.storage.provider}",
        title="Upload Complete",
    ))


# ============================================================================
# LEGACY COMMANDS (kept for backwards compatibility)
# ============================================================================


@app.command()
def generate(
    ctx: typer.Context,
    episode_id: Optional[str] = typer.Argument(None, help="Episode ID to generate script for (from preview)"),
    topic: Optional[str] = typer.Option(None, "--topic", "-t", help="Topic/premise for a new episode"),
) -> None:
    """[Legacy] Generate a complete episode with plot and script.

    Consider using 'brainwave new' instead for the improved pipeline.
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
    """[Legacy] Generate a plot-only preview (display only, not saved).

    Consider using 'brainwave new' instead for the improved pipeline.
    """
    config = ctx.obj["config"]
    generator = EpisodeGenerator(config)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Generating plot preview...", total=None)

        try:
            episode = generator.generate_preview(topic=topic)

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)

    # Show preview (not saved)
    console.print()
    console.print(Panel(
        f"[bold]Title:[/bold] {episode.plot.title if episode.plot else 'Untitled'}\n\n"
        f"[dim]This is a preview only and is not saved.[/dim]\n"
        f"[dim]Use 'brainwave new' for the full pipeline.[/dim]",
        title="Plot Preview",
    ))

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

    if mock:
        config.tts.provider = "mock"

    # Try pipeline first, fall back to legacy
    pipeline = EpisodePipeline(config)

    try:
        episode = pipeline.load(episode_id)
    except FileNotFoundError:
        # Try legacy manager
        manager = EpisodeManager(config.paths.scenes_dir)
        try:
            episode = manager.load(episode_id)
        except FileNotFoundError:
            console.print(f"[red]Episode not found: {episode_id}[/red]")
            raise typer.Exit(1)

    builder = EpisodeBuilder(config)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Building audio assets...", total=None)

        try:
            results = builder.build(episode, force=force)

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)

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
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip all confirmations"),
    mock: bool = typer.Option(False, "--mock", "-m", help="Use mock TTS"),
) -> None:
    """Generate multiple episodes in batch using the new pipeline."""
    config = ctx.obj["config"]

    if mock:
        config.tts.provider = "mock"

    pipeline = EpisodePipeline(config)

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
                confirm_cb = make_confirm_callback(True)  # Always auto-confirm in batch
                build_cb = make_build_callback(config)

                episode = pipeline.run_full(
                    topic=topic,
                    confirm_callback=confirm_cb,
                    build_callback=build_cb,
                )

                results_table.add_row(
                    episode.id_str[:8] + "...",
                    episode.title,
                    f"[green]{episode.meta.status.value}[/green]",
                )
                success_count += 1

            except Exception as e:
                results_table.add_row(
                    "N/A",
                    topic[:30] + "..." if topic and len(topic) > 30 else (topic or "Random"),
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

    # Try pipeline first, fall back to legacy
    pipeline = EpisodePipeline(config)
    manager = EpisodeManager(config.paths.scenes_dir)
    exporter = UnityExporter()

    try:
        episode = pipeline.load(episode_id)
        export_dir = episode.work_dir
    except FileNotFoundError:
        try:
            episode = manager.load(episode_id)
            export_dir = episode.work_dir
        except FileNotFoundError:
            console.print(f"[red]Episode not found: {episode_id}[/red]")
            raise typer.Exit(1)

    manifest_path = exporter.export(episode, export_dir)
    dialogs_path = exporter.export_dialog_list(episode, export_dir)

    console.print()
    console.print(Panel(
        f"[green]Export complete![/green]\n\n"
        f"[bold]Manifest:[/bold] {manifest_path}\n"
        f"[bold]Dialogs:[/bold] {dialogs_path}",
        title="Export Results",
    ))


@app.command("list")
def list_episodes(
    ctx: typer.Context,
    incomplete: bool = typer.Option(False, "--incomplete", "-i", help="Show only incomplete episodes"),
    completed: bool = typer.Option(False, "--completed", "-c", help="Show only completed (cloud) episodes"),
) -> None:
    """List episodes."""
    config = ctx.obj["config"]
    pipeline = EpisodePipeline(config)

    if incomplete:
        episodes = pipeline.list_incomplete()
        if not episodes:
            console.print("[yellow]No incomplete episodes found.[/yellow]")
            return
        _list_incomplete_episodes(episodes)

    elif completed:
        episodes = pipeline.list_completed()
        if not episodes:
            console.print("[yellow]No completed episodes found.[/yellow]")
            return

        table = Table(title="Completed Episodes (Cloud)")
        table.add_column("ID", style="cyan")
        table.add_column("Title")

        for episode_id, title in episodes[-20:]:
            table.add_row(
                episode_id[:8] + "...",
                title or "Untitled",
            )
        console.print(table)

    else:
        # Show both
        inc_episodes = pipeline.list_incomplete()
        comp_episodes = pipeline.list_completed()

        if inc_episodes:
            console.print("[bold]Incomplete Episodes:[/bold]")
            _list_incomplete_episodes(inc_episodes)
            console.print()

        if comp_episodes:
            console.print("[bold]Completed Episodes:[/bold]")
            table = Table()
            table.add_column("ID", style="cyan")
            table.add_column("Title")

            for episode_id, title in comp_episodes[-10:]:
                table.add_row(
                    episode_id[:8] + "...",
                    title or "Untitled",
                )
            console.print(table)

        if not inc_episodes and not comp_episodes:
            # Fall back to legacy
            manager = EpisodeManager(config.paths.scenes_dir)
            episode_ids = manager.list_episodes()

            if not episode_ids:
                console.print("[yellow]No episodes found.[/yellow]")
                return

            table = Table(title="Episodes (Legacy)")
            table.add_column("ID", style="cyan")
            table.add_column("Title")
            table.add_column("Status")

            for eid in episode_ids[-20:]:
                try:
                    ep = manager.load(eid)
                    table.add_row(
                        eid[:8] + "...",
                        ep.meta.title or "Untitled",
                        ep.meta.status.value,
                    )
                except Exception:
                    table.add_row(eid[:8] + "...", "[red]Error[/red]", "-")

            console.print(table)


@app.command()
def show(
    ctx: typer.Context,
    episode_id: str = typer.Argument(..., help="Episode ID to show"),
) -> None:
    """Show details of an episode."""
    config = ctx.obj["config"]

    # Try pipeline first, fall back to legacy
    pipeline = EpisodePipeline(config)
    manager = EpisodeManager(config.paths.scenes_dir)

    try:
        episode = pipeline.load(episode_id)
    except FileNotFoundError:
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


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def _show_episode_status(episode: Episode) -> None:
    """Display episode status after pipeline operations."""
    status_color = {
        EpisodeStatus.CREATED: "yellow",
        EpisodeStatus.OUTLINED: "blue",
        EpisodeStatus.SCRIPTED: "cyan",
        EpisodeStatus.BUILT: "magenta",
        EpisodeStatus.COMPLETED: "green",
        EpisodeStatus.FAILED: "red",
    }.get(episode.meta.status, "white")

    next_step = episode.meta.get_next_step()
    next_info = f"\n[dim]Next: brainwave resume {episode.id_str[:8]}...[/dim]" if next_step else ""

    console.print()
    console.print(Panel(
        f"[bold]ID:[/bold] {episode.id_str}\n"
        f"[bold]Title:[/bold] {episode.title}\n"
        f"[bold]Status:[/bold] [{status_color}]{episode.meta.status.value}[/{status_color}]\n"
        f"[bold]Scenes:[/bold] {episode.meta.scene_count or '-'}\n"
        f"[bold]Dialog lines:[/bold] {episode.meta.dialog_count or '-'}"
        f"{next_info}",
        title="Episode Status",
    ))


def _list_incomplete_episodes(episodes: list[tuple[str, EpisodeStatus, str | None]]) -> None:
    """Display incomplete episodes table."""
    table = Table(title="Incomplete Episodes")
    table.add_column("ID", style="cyan")
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Next Step")

    for episode_id, status, title in episodes:
        from brainwave.models.episode import EpisodeMeta
        meta = EpisodeMeta(status=status)
        next_step = meta.get_next_step()

        table.add_row(
            episode_id[:8] + "...",
            title or "Untitled",
            status.value,
            next_step.value if next_step else "-",
        )

    console.print(table)


if __name__ == "__main__":
    app()
