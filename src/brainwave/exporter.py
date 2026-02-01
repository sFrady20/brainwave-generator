"""Export episode data to Unity-compatible formats."""

import json
from pathlib import Path
from typing import Any

import structlog

from brainwave.models.episode import Episode
from brainwave.models.script import WaveLangScript
from brainwave.parser import WaveLangParser

logger = structlog.get_logger()


class UnityExporter:
    """Export episode data to Unity-compatible JSON manifest."""

    VERSION = "1.0"

    def __init__(self):
        self.parser = WaveLangParser()

    def export(self, episode: Episode, output_dir: Path | None = None) -> Path:
        """
        Generate Unity manifest JSON for an episode.

        Creates a manifest.json file with structured scene and dialog data
        that the Unity application can use for rendering.

        Args:
            episode: Episode to export
            output_dir: Optional output directory (defaults to episode work_dir)

        Returns:
            Path to generated manifest.json
        """
        if output_dir is None:
            if episode.work_dir is None:
                raise ValueError("Episode must have work_dir set or output_dir provided")
            output_dir = episode.work_dir

        output_dir.mkdir(parents=True, exist_ok=True)

        # Parse script if available
        script: WaveLangScript | None = None
        if episode.script_raw:
            script = self.parser.parse(episode.script_raw)

        manifest = self._build_manifest(episode, script)

        output_path = output_dir / "manifest.json"
        with open(output_path, "w") as f:
            json.dump(manifest, f, indent=2)

        logger.info("manifest_exported", path=str(output_path))
        return output_path

    def _build_manifest(
        self,
        episode: Episode,
        script: WaveLangScript | None,
    ) -> dict[str, Any]:
        """Build the manifest dictionary."""
        manifest: dict[str, Any] = {
            "version": self.VERSION,
            "episode_id": str(episode.id),
            "title": episode.meta.title or "Untitled Episode",
            "status": episode.meta.status.value,
            "created_at": episode.meta.created_at.isoformat() if episode.meta.created_at else None,
        }

        # Add plot summary if available
        if episode.plot:
            manifest["plot"] = {
                "title": episode.plot.title,
                "beats": [
                    {"name": beat.name, "summary": beat.content[:200] + "..." if len(beat.content) > 200 else beat.content}
                    for beat in episode.plot.beats
                ],
            }

        # Add scenes if script is available
        if script:
            manifest["scenes"] = []
            manifest["total_scenes"] = script.scene_count
            manifest["total_dialog_lines"] = script.dialog_count

            for scene_idx, scene in enumerate(script.scenes):
                scene_data: dict[str, Any] = {
                    "index": scene_idx,
                    "shot_id": scene.header.shot_id,
                    "character_count": scene.header.character_count,
                    "max_characters": scene.header.max_characters,
                    "characters": scene.header.characters,
                    "dialog": [],
                }

                for dialog in scene.dialog:
                    scene_data["dialog"].append({
                        "character": dialog.character,
                        "inflection": dialog.inflection,
                        "text": dialog.text,
                        "audio_file": f"dialog-{dialog.line_number}.mp3",
                        "line_number": dialog.line_number,
                    })

                manifest["scenes"].append(scene_data)

        return manifest

    def export_dialog_list(self, episode: Episode, output_dir: Path | None = None) -> Path:
        """
        Export a simple dialog list for TTS processing.

        Creates a dialogs.json file with just the dialog lines and their
        associated metadata for audio generation.

        Args:
            episode: Episode to export
            output_dir: Optional output directory

        Returns:
            Path to generated dialogs.json
        """
        if output_dir is None:
            if episode.work_dir is None:
                raise ValueError("Episode must have work_dir set or output_dir provided")
            output_dir = episode.work_dir

        output_dir.mkdir(parents=True, exist_ok=True)

        dialogs: list[dict[str, Any]] = []

        if episode.script_raw:
            script = self.parser.parse(episode.script_raw)

            for dialog in script.all_dialog_lines:
                dialogs.append({
                    "line_number": dialog.line_number,
                    "character": dialog.character,
                    "inflection": dialog.inflection,
                    "text": dialog.text,
                    "audio_file": f"dialog-{dialog.line_number}.mp3",
                })

        output_path = output_dir / "dialogs.json"
        with open(output_path, "w") as f:
            json.dump({"dialogs": dialogs, "count": len(dialogs)}, f, indent=2)

        logger.info("dialogs_exported", path=str(output_path), count=len(dialogs))
        return output_path


def generate_preview_text(episode: Episode) -> str:
    """
    Generate a human-readable preview of an episode.

    Args:
        episode: Episode to preview

    Returns:
        Formatted markdown preview string
    """
    lines = []

    if episode.plot:
        lines.append(f"# {episode.plot.title}")
        lines.append("")
        lines.append("## Plot Summary")
        lines.append("")

        for beat in episode.plot.beats:
            beat_name = beat.name.replace("_", " ").title()
            lines.append(f"**{beat_name}:** {beat.content}")
            lines.append("")

    if episode.script_raw:
        parser = WaveLangParser()
        script = parser.parse(episode.script_raw)

        lines.append("## Scene Breakdown")
        lines.append("")
        lines.append(f"Total Scenes: {script.scene_count}")
        lines.append(f"Total Dialog Lines: {script.dialog_count}")
        lines.append("")

        for i, scene in enumerate(script.scenes, 1):
            chars = ", ".join(scene.header.characters)
            lines.append(f"### Scene {i} (Shot {scene.header.shot_id})")
            lines.append(f"*Characters: {chars}*")
            lines.append("")

            # Show first few dialog lines
            for dialog in scene.dialog[:3]:
                text = dialog.text[:80] + "..." if len(dialog.text) > 80 else dialog.text
                lines.append(f"> **{dialog.character}** ({dialog.inflection}): {text}")

            if len(scene.dialog) > 3:
                lines.append(f"*...and {len(scene.dialog) - 3} more lines*")

            lines.append("")

    return "\n".join(lines)
