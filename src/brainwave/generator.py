"""Episode generation using single-shot LLM calls."""

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

import structlog
from jinja2 import Environment, FileSystemLoader
from openai import OpenAI

from brainwave.config import AppConfig
from brainwave.models.characters import CharacterRegistry, ShotRegistry, load_characters, load_shots
from brainwave.models.episode import Episode, EpisodeMeta, EpisodePlot, EpisodeStatus, PlotBeat
from brainwave.models.script import WaveLangScript
from brainwave.parser import PlotParser, WaveLangParser
from brainwave.validator import ScriptValidator

logger = structlog.get_logger()


class EpisodeGenerator:
    """
    Generates complete episodes in a single LLM call.

    The new approach consolidates plot and script generation into one
    prompt, leveraging modern LLMs' large context windows for better
    coherence and consistency.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.wavlang_parser = WaveLangParser()
        self.plot_parser = PlotParser()

        # Load character and shot data
        self.characters = load_characters(config.paths.data_dir / "characters.yaml")
        self.shots = load_shots(config.paths.data_dir / "shots.yaml")

        # Set up validator
        self.validator = ScriptValidator(self.characters, self.shots)

        # Set up Jinja2 environment
        self.jinja_env = Environment(
            loader=FileSystemLoader(config.paths.templates_dir),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # Set up OpenAI client
        api_key = config.llm.api_key.get_secret_value() if config.llm.api_key else None
        self.client = OpenAI(
            api_key=api_key,
            base_url=config.llm.base_url,
            timeout=config.llm.timeout,
        )

    def generate(
        self,
        topic: str | None = None,
        max_retries: int = 3,
    ) -> Episode:
        """
        Generate a complete episode with plot and script.

        Args:
            topic: Optional specific topic/premise for the episode
            max_retries: Number of retry attempts on validation failure

        Returns:
            Complete Episode with plot and WaveLang script
        """
        episode = Episode.new(topic=topic)
        episode.meta.model_used = self.config.llm.model

        # Build the consolidated prompt
        prompt = self._build_episode_prompt(topic=topic)

        for attempt in range(max_retries):
            try:
                logger.info(
                    "generating_episode",
                    attempt=attempt + 1,
                    model=self.config.llm.model,
                    topic=topic,
                )

                response = self.client.chat.completions.create(
                    model=self.config.llm.model,
                    messages=prompt,
                    temperature=self.config.llm.temperature,
                )

                content = response.choices[0].message.content
                if not content:
                    raise ValueError("Empty response from LLM")

                if response.usage:
                    episode.meta.generation_tokens = response.usage.total_tokens

                # Parse the response into plot + script
                plot_text, script_text = self.wavlang_parser.extract_plot_and_script(content)

                # Parse plot
                plot_data = self.plot_parser.parse(plot_text)
                episode.plot = self._build_plot(plot_data, plot_text)
                episode.meta.title = episode.plot.title

                # Parse script
                script = self.wavlang_parser.parse(script_text)
                episode.script_raw = script_text
                episode.meta.scene_count = script.scene_count
                episode.meta.dialog_count = script.dialog_count

                # Validate the script
                validation_result = self.validator.validate(script)
                if not validation_result.is_valid:
                    logger.warning(
                        "validation_failed",
                        errors=[e.message for e in validation_result.errors],
                        attempt=attempt + 1,
                    )
                    if attempt < max_retries - 1:
                        continue
                    # On final attempt, return with warnings
                    logger.warning("returning_with_validation_errors")

                episode.meta.status = EpisodeStatus.SCRIPT_GENERATED
                logger.info(
                    "episode_generated",
                    title=episode.plot.title,
                    scenes=script.scene_count,
                    dialogs=script.dialog_count,
                )

                return episode

            except Exception as e:
                logger.error("generation_failed", error=str(e), attempt=attempt + 1)
                if attempt == max_retries - 1:
                    episode.meta.status = EpisodeStatus.FAILED
                    raise

        raise RuntimeError("Episode generation failed after max retries")

    def generate_preview(self, topic: str | None = None) -> Episode:
        """
        Generate plot-only preview (no full script).

        Args:
            topic: Optional specific topic/premise

        Returns:
            Episode with plot but no script
        """
        episode = Episode.new(topic=topic)
        episode.meta.model_used = self.config.llm.model

        prompt = self._build_preview_prompt(topic=topic)

        logger.info("generating_preview", model=self.config.llm.model, topic=topic)

        response = self.client.chat.completions.create(
            model=self.config.llm.model,
            messages=prompt,
            temperature=self.config.llm.temperature,
        )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty response from LLM")

        if response.usage:
            episode.meta.generation_tokens = response.usage.total_tokens

        # Extract plot section
        plot_text, _ = self.wavlang_parser.extract_plot_and_script(content + "\n=== SCRIPT ===\n")

        # Parse plot
        plot_data = self.plot_parser.parse(plot_text)
        episode.plot = self._build_plot(plot_data, plot_text)
        episode.meta.title = episode.plot.title
        episode.meta.status = EpisodeStatus.PLOT_GENERATED

        logger.info("preview_generated", title=episode.plot.title)

        return episode

    def generate_from_plot(self, episode: Episode, max_retries: int = 3) -> Episode:
        """
        Generate full script from existing plot.

        Args:
            episode: Episode with plot already generated
            max_retries: Number of retry attempts

        Returns:
            Episode with full script added
        """
        if not episode.plot:
            raise ValueError("Episode must have a plot to generate script from")

        # Build prompt with existing plot
        prompt = self._build_episode_prompt(
            topic=episode.meta.topic,
            existing_plot=episode.plot,
        )

        for attempt in range(max_retries):
            try:
                logger.info(
                    "generating_script_from_plot",
                    attempt=attempt + 1,
                    title=episode.plot.title,
                )

                response = self.client.chat.completions.create(
                    model=self.config.llm.model,
                    messages=prompt,
                    temperature=self.config.llm.temperature,
                )

                content = response.choices[0].message.content
                if not content:
                    raise ValueError("Empty response from LLM")

                # Parse script from response - it may or may not have section markers
                script_text = content

                # Try to extract just the script section if markers are present
                if "=== SCRIPT ===" in content:
                    try:
                        _, script_text = self.wavlang_parser.extract_plot_and_script(content)
                    except ValueError:
                        # If extraction fails, use the whole content
                        pass

                # Clean up any markdown code blocks
                script_text = script_text.strip()
                if script_text.startswith("```"):
                    lines = script_text.split("\n")
                    script_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

                script = self.wavlang_parser.parse(script_text)

                episode.script_raw = script_text
                episode.meta.scene_count = script.scene_count
                episode.meta.dialog_count = script.dialog_count

                # Validate
                validation_result = self.validator.validate(script)
                if not validation_result.is_valid and attempt < max_retries - 1:
                    logger.warning("validation_failed", attempt=attempt + 1)
                    continue

                episode.meta.status = EpisodeStatus.SCRIPT_GENERATED
                return episode

            except Exception as e:
                logger.error("script_generation_failed", error=str(e), attempt=attempt + 1)
                if attempt == max_retries - 1:
                    raise

        raise RuntimeError("Script generation failed after max retries")

    def _build_episode_prompt(
        self,
        topic: str | None = None,
        existing_plot: EpisodePlot | None = None,
    ) -> list[dict[str, str]]:
        """Build the full episode generation prompt."""
        template = self.jinja_env.get_template("episode.md.j2")

        system_content = template.render(
            characters=self.characters.characters,
            shots=self.shots.shots,
            topic=topic,
        )

        messages = [{"role": "system", "content": system_content}]

        if existing_plot:
            # Add the existing plot to generate script for it
            plot_text = self._format_plot_for_prompt(existing_plot)
            messages.append({
                "role": "user",
                "content": (
                    f"Generate the full WaveLang script for this existing plot. "
                    f"Output ONLY the WaveLang script (scene headers and dialog), no plot section needed.\n\n"
                    f"PLOT:\n{plot_text}\n\n"
                    f"Generate 10-20 scenes covering all plot beats. Start directly with the first scene header (>>)."
                ),
            })
        else:
            messages.append({
                "role": "user",
                "content": "Generate a complete episode with plot and full WaveLang script.",
            })

        return messages

    def _build_preview_prompt(self, topic: str | None = None) -> list[dict[str, str]]:
        """Build the plot-only preview prompt."""
        template = self.jinja_env.get_template("preview.md.j2")

        system_content = template.render(
            characters=self.characters.characters,
            topic=topic,
        )

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": "Generate an episode plot outline."},
        ]

    def _build_plot(self, plot_data: dict[str, str], raw_text: str) -> EpisodePlot:
        """Build EpisodePlot from parsed data."""
        beats = []
        for beat_name in ["exposition", "rising_action", "climax", "falling_action", "resolution"]:
            if beat_name in plot_data:
                beats.append(PlotBeat(name=beat_name, content=plot_data[beat_name]))

        return EpisodePlot(
            title=plot_data.get("title", "Untitled Episode"),
            beats=beats,
            raw_text=raw_text,
        )

    def _format_plot_for_prompt(self, plot: EpisodePlot) -> str:
        """Format plot for inclusion in prompt."""
        lines = [f"title: {plot.title}"]
        for beat in plot.beats:
            lines.append(f"{beat.name}: {beat.content}")
        return "\n".join(lines)


class EpisodeManager:
    """Manages episode file I/O."""

    def __init__(self, scenes_dir: Path):
        self.scenes_dir = scenes_dir
        self.scenes_dir.mkdir(parents=True, exist_ok=True)

    def get_episode_dir(self, episode_id: str | UUID) -> Path:
        """Get the directory for an episode."""
        return self.scenes_dir / str(episode_id)

    def save(self, episode: Episode) -> Path:
        """
        Save an episode to disk.

        Creates:
        - meta.json - Episode metadata
        - episode-plot.txt - Plot text
        - episode-script.txt - WaveLang script

        Returns:
            Path to episode directory
        """
        episode_dir = self.get_episode_dir(episode.id)
        episode_dir.mkdir(parents=True, exist_ok=True)

        # Save metadata
        meta_path = episode_dir / "meta.json"
        with open(meta_path, "w") as f:
            json.dump(episode.meta.model_dump_json_compatible(), f, indent=2)

        # Save plot
        if episode.plot:
            plot_path = episode_dir / "episode-plot.txt"
            with open(plot_path, "w") as f:
                f.write(episode.plot.raw_text)

        # Save script
        if episode.script_raw:
            script_path = episode_dir / "episode-script.txt"
            with open(script_path, "w") as f:
                f.write(episode.script_raw)

        episode.work_dir = episode_dir

        logger.info("episode_saved", path=str(episode_dir))
        return episode_dir

    def load(self, episode_id: str) -> Episode:
        """
        Load an episode from disk.

        Args:
            episode_id: Episode UUID string

        Returns:
            Loaded Episode instance
        """
        episode_dir = self.get_episode_dir(episode_id)

        if not episode_dir.exists():
            raise FileNotFoundError(f"Episode not found: {episode_id}")

        # Load metadata
        meta_path = episode_dir / "meta.json"
        with open(meta_path) as f:
            meta_data = json.load(f)

        # Convert back to proper types
        meta_data["id"] = UUID(meta_data["id"])
        meta_data["status"] = EpisodeStatus(meta_data["status"])
        if meta_data.get("created_at"):
            meta_data["created_at"] = datetime.fromisoformat(meta_data["created_at"])
        if meta_data.get("completed_at"):
            meta_data["completed_at"] = datetime.fromisoformat(meta_data["completed_at"])

        meta = EpisodeMeta(**meta_data)

        # Load plot if exists
        plot = None
        plot_path = episode_dir / "episode-plot.txt"
        if plot_path.exists():
            with open(plot_path) as f:
                plot_text = f.read()
            parser = PlotParser()
            plot_data = parser.parse(plot_text)
            plot = EpisodePlot(
                title=plot_data.get("title", meta.title or "Untitled"),
                beats=[
                    PlotBeat(name=name, content=content)
                    for name, content in plot_data.items()
                    if name != "title"
                ],
                raw_text=plot_text,
            )

        # Load script if exists
        script_raw = None
        script_path = episode_dir / "episode-script.txt"
        if script_path.exists():
            with open(script_path) as f:
                script_raw = f.read()

        return Episode(
            meta=meta,
            plot=plot,
            script_raw=script_raw,
            work_dir=episode_dir,
        )

    def list_episodes(self) -> list[str]:
        """List all episode IDs."""
        episodes = []
        for path in self.scenes_dir.iterdir():
            if path.is_dir() and (path / "meta.json").exists():
                episodes.append(path.name)
        return sorted(episodes)

    def create_assets_dir(self, episode: Episode) -> Path:
        """Create assets/sfx directory for an episode."""
        if not episode.work_dir:
            episode.work_dir = self.get_episode_dir(episode.id)

        sfx_dir = episode.work_dir / "assets" / "sfx"
        sfx_dir.mkdir(parents=True, exist_ok=True)
        return sfx_dir
