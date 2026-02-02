"""Unified episode generation pipeline."""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable
from uuid import UUID

import structlog
from jinja2 import Environment, FileSystemLoader
from openai import OpenAI

from brainwave.config import AppConfig
from brainwave.models.characters import load_characters, load_shots
from brainwave.models.episode import (
    Episode,
    EpisodeMeta,
    EpisodeOutline,
    EpisodeStatus,
    PipelineStep,
    SceneBeat,
)
from brainwave.parser import WaveLangParser
from brainwave.storage import StorageProvider, create_storage_provider
from brainwave.validator import ScriptValidator

logger = structlog.get_logger()


class OutlineParser:
    """Parse LLM outline output into structured data."""

    def parse(self, content: str) -> EpisodeOutline:
        """Parse outline text into EpisodeOutline."""
        lines = content.strip().split("\n")

        title = "Untitled Episode"
        premise = ""
        theme = None
        scenes: list[SceneBeat] = []
        callbacks: list[str] = []
        ending = None

        current_section = None
        current_scene: dict | None = None
        scene_num = 0

        for line in lines:
            line_stripped = line.strip()

            # Skip empty lines and markers
            if not line_stripped or line_stripped == "=== OUTLINE ===":
                continue

            # Parse top-level fields
            if line_stripped.startswith("title:"):
                title = line_stripped[6:].strip()
                current_section = None
            elif line_stripped.startswith("premise:"):
                premise = line_stripped[8:].strip()
                current_section = None
            elif line_stripped.startswith("theme:"):
                theme = line_stripped[6:].strip()
                current_section = None
            elif line_stripped.startswith("ending:"):
                ending = line_stripped[7:].strip()
                current_section = None
            elif line_stripped.startswith("scenes:"):
                current_section = "scenes"
            elif line_stripped.startswith("callbacks:"):
                current_section = "callbacks"
            elif current_section == "scenes":
                # Parse scene lines
                if line_stripped[0].isdigit() and ("." in line_stripped or "[" in line_stripped):
                    # New scene: "1. [Shot 16] - Art, Nia, Dave"
                    if current_scene:
                        scenes.append(self._build_scene_beat(current_scene))

                    scene_num += 1
                    current_scene = {
                        "scene_num": scene_num,
                        "shot_id": self._extract_shot_id(line_stripped),
                        "characters": self._extract_characters(line_stripped),
                        "setup": "",
                        "beat": "",
                        "lands": "",
                    }
                elif current_scene:
                    # Scene detail lines
                    if line_stripped.startswith("- Setup:"):
                        current_scene["setup"] = line_stripped[8:].strip()
                    elif line_stripped.startswith("- Beat:"):
                        current_scene["beat"] = line_stripped[7:].strip()
                    elif line_stripped.startswith("- Lands:"):
                        current_scene["lands"] = line_stripped[8:].strip()
            elif current_section == "callbacks":
                if line_stripped.startswith("-"):
                    callbacks.append(line_stripped[1:].strip())

        # Don't forget the last scene
        if current_scene:
            scenes.append(self._build_scene_beat(current_scene))

        return EpisodeOutline(
            title=title,
            premise=premise,
            theme=theme,
            scenes=scenes,
            callbacks=callbacks,
            ending=ending,
            raw_text=content,
        )

    def _extract_shot_id(self, line: str) -> int:
        """Extract shot ID from scene line like '1. [Shot 16] - ...'"""
        import re

        match = re.search(r"\[(?:Shot\s*)?(\d+)\]", line, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return 1

    def _extract_characters(self, line: str) -> list[str]:
        """Extract character names from scene line."""
        # Look for part after ' - '
        if " - " in line:
            chars_part = line.split(" - ", 1)[1]
            return [c.strip() for c in chars_part.split(",") if c.strip()]
        return []

    def _build_scene_beat(self, data: dict) -> SceneBeat:
        """Build SceneBeat from parsed data."""
        return SceneBeat(
            scene_num=data["scene_num"],
            shot_id=data["shot_id"],
            characters=data["characters"],
            setup=data["setup"],
            beat=data["beat"],
            lands=data["lands"],
        )


class EpisodePipeline:
    """
    Unified pipeline for episode generation.

    Handles the full flow: Topic → Outline → Script → Build → Complete
    with checkpoints at each step for resume capability.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.incomplete_dir = config.paths.incomplete_dir
        self.incomplete_dir.mkdir(parents=True, exist_ok=True)

        # Load character and shot data
        self.characters = load_characters(config.paths.data_dir / "characters.yaml")
        self.shots = load_shots(config.paths.data_dir / "shots.yaml")

        # Set up components
        self.wavlang_parser = WaveLangParser()
        self.outline_parser = OutlineParser()
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

        # Storage provider is lazily initialized (only needed for complete step)
        self._storage: StorageProvider | None = None

    @property
    def storage(self) -> StorageProvider:
        """Lazily initialize storage provider."""
        if self._storage is None:
            self._storage = create_storage_provider(self.config.storage, self.config.paths.scenes_dir)
        return self._storage

    def create(self, topic: str | None = None) -> Episode:
        """
        Create a new episode and save it to incomplete directory.

        Args:
            topic: Optional topic/premise for the episode

        Returns:
            New episode in CREATED state
        """
        episode = Episode.new(topic=topic)
        episode.meta.model_used = self.config.llm.model
        episode.work_dir = self.incomplete_dir / episode.id_str
        episode.work_dir.mkdir(parents=True, exist_ok=True)

        self._save_episode(episode)

        logger.info("episode_created", episode_id=episode.id_str, topic=topic)
        return episode

    def run_outline(self, episode: Episode) -> Episode:
        """
        Generate episode outline (Step 1).

        Args:
            episode: Episode to generate outline for

        Returns:
            Episode with outline populated
        """
        if episode.meta.status not in (EpisodeStatus.CREATED, EpisodeStatus.PENDING):
            raise ValueError(f"Cannot run outline step on episode with status: {episode.meta.status}")

        logger.info("generating_outline", episode_id=episode.id_str, topic=episode.meta.topic)

        # Build outline prompt
        prompt = self._build_outline_prompt(episode.meta.topic)

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

        # Parse outline
        outline = self.outline_parser.parse(content)
        episode.outline = outline
        episode.meta.title = outline.title
        episode.meta.status = EpisodeStatus.OUTLINED
        episode.meta.mark_step_completed(PipelineStep.OUTLINE)
        episode.meta.current_step = PipelineStep.SCRIPT.value

        # Save outline to file
        self._save_episode(episode)
        if episode.work_dir:
            outline_path = episode.work_dir / "outline.txt"
            with open(outline_path, "w", encoding="utf-8") as f:
                f.write(content)

        logger.info(
            "outline_generated",
            episode_id=episode.id_str,
            title=outline.title,
            scenes=len(outline.scenes),
        )

        return episode

    def run_script(self, episode: Episode) -> Episode:
        """
        Generate full script from outline (Step 2).

        Args:
            episode: Episode with outline to generate script for

        Returns:
            Episode with script populated
        """
        if episode.meta.status not in (
            EpisodeStatus.OUTLINED,
            EpisodeStatus.PLOT_GENERATED,  # Legacy
        ):
            raise ValueError(f"Cannot run script step on episode with status: {episode.meta.status}")

        if not episode.outline and not episode.plot:
            raise ValueError("Episode must have outline or plot to generate script")

        logger.info("generating_script", episode_id=episode.id_str, title=episode.title)

        # Build script prompt
        outline_text = episode.outline.raw_text if episode.outline else ""
        if not outline_text and episode.plot:
            # Legacy: convert plot to outline-like text
            outline_text = self._plot_to_outline_text(episode.plot)

        prompt = self._build_script_prompt(outline_text)

        response = self.client.chat.completions.create(
            model=self.config.llm.model,
            messages=prompt,
            temperature=self.config.llm.temperature,
        )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty response from LLM")

        # Clean up any markdown code blocks
        script_text = content.strip()
        if script_text.startswith("```"):
            lines = script_text.split("\n")
            script_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        # Parse and validate script
        script = self.wavlang_parser.parse(script_text)

        episode.script_raw = script_text
        episode.meta.scene_count = script.scene_count
        episode.meta.dialog_count = script.dialog_count
        episode.meta.status = EpisodeStatus.SCRIPTED
        episode.meta.mark_step_completed(PipelineStep.SCRIPT)
        episode.meta.current_step = PipelineStep.BUILD.value

        # Validate
        validation_result = self.validator.validate(script)
        if not validation_result.is_valid:
            logger.warning(
                "script_validation_warnings",
                episode_id=episode.id_str,
                errors=[e.message for e in validation_result.errors],
            )

        # Save script to file
        self._save_episode(episode)
        if episode.work_dir:
            script_path = episode.work_dir / "episode-script.txt"
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(script_text)

        logger.info(
            "script_generated",
            episode_id=episode.id_str,
            scenes=script.scene_count,
            dialogs=script.dialog_count,
        )

        return episode

    def run_build(
        self,
        episode: Episode,
        build_callback: Callable[[Episode], Episode] | None = None,
    ) -> Episode:
        """
        Build TTS audio for episode (Step 3).

        Args:
            episode: Episode with script to build audio for
            build_callback: Optional callback function that does the actual TTS generation

        Returns:
            Episode with audio built
        """
        if episode.meta.status not in (
            EpisodeStatus.SCRIPTED,
            EpisodeStatus.SCRIPT_GENERATED,  # Legacy
        ):
            raise ValueError(f"Cannot run build step on episode with status: {episode.meta.status}")

        if not episode.script_raw:
            raise ValueError("Episode must have script to build")

        logger.info("building_audio", episode_id=episode.id_str)

        if build_callback:
            episode = build_callback(episode)
        else:
            # If no callback provided, just mark as built (mock mode)
            logger.warning("no_build_callback", episode_id=episode.id_str)
            episode.meta.build_mocked = True

        episode.meta.status = EpisodeStatus.BUILT
        episode.meta.mark_step_completed(PipelineStep.BUILD)
        episode.meta.current_step = PipelineStep.COMPLETE.value

        self._save_episode(episode)

        logger.info("audio_built", episode_id=episode.id_str)
        return episode

    def run_complete(self, episode: Episode) -> Episode:
        """
        Upload episode to cloud storage (Step 4).

        Args:
            episode: Episode to upload

        Returns:
            Completed episode
        """
        if episode.meta.status != EpisodeStatus.BUILT:
            raise ValueError(f"Cannot complete episode with status: {episode.meta.status}")

        if not episode.work_dir:
            raise ValueError("Episode has no work directory")

        logger.info("completing_episode", episode_id=episode.id_str)

        # Upload to cloud storage
        remote_path = self.storage.upload_episode(episode.work_dir, episode.id_str)

        # Update status
        episode.meta.status = EpisodeStatus.COMPLETED
        episode.meta.completed_at = datetime.now()
        episode.meta.mark_step_completed(PipelineStep.COMPLETE)
        episode.meta.current_step = None

        # Save final meta before cleanup
        self._save_episode(episode)

        # Remove from incomplete directory
        if episode.work_dir and episode.work_dir.exists():
            shutil.rmtree(episode.work_dir)
            logger.info("incomplete_dir_cleaned", path=str(episode.work_dir))

        episode.work_dir = None

        logger.info(
            "episode_completed",
            episode_id=episode.id_str,
            remote_path=remote_path,
        )

        return episode

    def run_full(
        self,
        topic: str | None = None,
        confirm_callback: Callable[[Episode, PipelineStep], bool] | None = None,
        build_callback: Callable[[Episode], Episode] | None = None,
    ) -> Episode:
        """
        Run the full pipeline with optional confirmation at each step.

        Args:
            topic: Optional topic for the episode
            confirm_callback: Function that returns True to continue, False to pause
            build_callback: Function to build TTS audio

        Returns:
            Episode (may be incomplete if paused)
        """
        episode = self.create(topic)

        steps = [
            (PipelineStep.OUTLINE, self.run_outline),
            (PipelineStep.SCRIPT, self.run_script),
            (PipelineStep.BUILD, lambda ep: self.run_build(ep, build_callback)),
            (PipelineStep.COMPLETE, self.run_complete),
        ]

        for step, runner in steps:
            episode = runner(episode)

            if confirm_callback and step != PipelineStep.COMPLETE:
                if not confirm_callback(episode, step):
                    logger.info("pipeline_paused", episode_id=episode.id_str, step=step.value)
                    return episode

        return episode

    def resume(
        self,
        episode_id: str,
        confirm_callback: Callable[[Episode, PipelineStep], bool] | None = None,
        build_callback: Callable[[Episode], Episode] | None = None,
    ) -> Episode:
        """
        Resume a paused episode from its current step.

        Args:
            episode_id: Episode ID to resume
            confirm_callback: Function that returns True to continue, False to pause
            build_callback: Function to build TTS audio

        Returns:
            Episode (may still be incomplete if paused again)
        """
        episode = self.load(episode_id)

        if not episode.can_resume():
            raise ValueError(f"Episode {episode_id} cannot be resumed (status: {episode.meta.status})")

        next_step = episode.meta.get_next_step()
        if not next_step:
            logger.info("episode_already_complete", episode_id=episode_id)
            return episode

        logger.info("resuming_episode", episode_id=episode_id, next_step=next_step.value)

        # Build remaining steps
        all_steps = [
            (PipelineStep.OUTLINE, self.run_outline),
            (PipelineStep.SCRIPT, self.run_script),
            (PipelineStep.BUILD, lambda ep: self.run_build(ep, build_callback)),
            (PipelineStep.COMPLETE, self.run_complete),
        ]

        # Find where to start
        start_idx = next((i for i, (s, _) in enumerate(all_steps) if s == next_step), 0)

        for step, runner in all_steps[start_idx:]:
            episode = runner(episode)

            if confirm_callback and step != PipelineStep.COMPLETE:
                if not confirm_callback(episode, step):
                    logger.info("pipeline_paused", episode_id=episode.id_str, step=step.value)
                    return episode

        return episode

    def load(self, episode_id: str) -> Episode:
        """
        Load an episode from incomplete directory.

        Args:
            episode_id: Episode UUID string

        Returns:
            Loaded Episode instance
        """
        episode_dir = self.incomplete_dir / episode_id

        if not episode_dir.exists():
            raise FileNotFoundError(f"Episode not found: {episode_id}")

        # Load metadata
        meta_path = episode_dir / "meta.json"
        with open(meta_path, encoding="utf-8") as f:
            meta_data = json.load(f)

        # Convert back to proper types
        meta_data["id"] = UUID(meta_data["id"])
        meta_data["status"] = EpisodeStatus(meta_data["status"])
        if meta_data.get("created_at"):
            meta_data["created_at"] = datetime.fromisoformat(meta_data["created_at"])
        if meta_data.get("completed_at"):
            meta_data["completed_at"] = datetime.fromisoformat(meta_data["completed_at"])

        meta = EpisodeMeta(**meta_data)

        # Load outline if exists
        outline = None
        outline_path = episode_dir / "outline.txt"
        if outline_path.exists():
            with open(outline_path, encoding="utf-8") as f:
                outline_text = f.read()
            outline = self.outline_parser.parse(outline_text)

        # Load script if exists
        script_raw = None
        script_path = episode_dir / "episode-script.txt"
        if script_path.exists():
            with open(script_path, encoding="utf-8") as f:
                script_raw = f.read()

        return Episode(
            meta=meta,
            outline=outline,
            script_raw=script_raw,
            work_dir=episode_dir,
        )

    def list_incomplete(self) -> list[tuple[str, EpisodeStatus, str | None]]:
        """
        List all incomplete episodes.

        Returns:
            List of (episode_id, status, title) tuples
        """
        episodes = []
        for path in self.incomplete_dir.iterdir():
            if path.is_dir() and (path / "meta.json").exists():
                try:
                    with open(path / "meta.json", encoding="utf-8") as f:
                        meta = json.load(f)
                    episodes.append((
                        path.name,
                        EpisodeStatus(meta.get("status", "created")),
                        meta.get("title"),
                    ))
                except Exception:
                    pass
        return sorted(episodes, key=lambda x: x[0])

    def list_completed(self) -> list[tuple[str, str | None]]:
        """
        List all completed episodes in storage.

        Returns:
            List of (episode_id, title) tuples
        """
        episodes = []
        for episode_id in self.storage.list_episodes():
            meta = self.storage.get_episode_meta(episode_id)
            title = meta.get("title") if meta else None
            episodes.append((episode_id, title))
        return episodes

    def _save_episode(self, episode: Episode) -> None:
        """Save episode state to disk."""
        if not episode.work_dir:
            episode.work_dir = self.incomplete_dir / episode.id_str
            episode.work_dir.mkdir(parents=True, exist_ok=True)

        meta_path = episode.work_dir / "meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(episode.meta.model_dump_json_compatible(), f, indent=2)

    def _build_outline_prompt(self, topic: str | None) -> list[dict[str, str]]:
        """Build the outline generation prompt."""
        template = self.jinja_env.get_template("outline.md.j2")

        system_content = template.render(
            characters=self.characters.characters,
            shots=self.shots.shots,
            topic=topic,
        )

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": f"Create an episode outline for: {topic or 'any topic you find interesting'}"},
        ]

    def _build_script_prompt(self, outline_text: str) -> list[dict[str, str]]:
        """Build the script generation prompt."""
        template = self.jinja_env.get_template("script.md.j2")

        system_content = template.render(
            characters=self.characters.characters,
            shots=self.shots.shots,
            outline=outline_text,
        )

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": "Write the full WaveLang script for this outline."},
        ]

    def _plot_to_outline_text(self, plot) -> str:
        """Convert legacy plot to outline-like text for script generation."""
        lines = [f"title: {plot.title}"]
        for beat in plot.beats:
            lines.append(f"{beat.name}: {beat.content}")
        return "\n".join(lines)
