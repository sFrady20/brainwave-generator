"""WaveLang script parser."""

import re
from dataclasses import dataclass

import structlog

from brainwave.models.script import DialogLine, Scene, SceneHeader, WaveLangScript

logger = structlog.get_logger()


@dataclass
class ParseError:
    """Represents a parsing error or warning."""

    line_number: int
    message: str
    raw_line: str


class WaveLangParser:
    """
    Parser for WaveLang script format.

    WaveLang format:
    - Scene header: >> [shot_id] > count/max - Character1, Character2
    - Dialog: :: character : inflection : text
    - Summary: == summary text
    """

    # Pattern for scene headers: >> [12] > 3/4 - Marcus, David, Carmen
    SCENE_HEADER_PATTERN = re.compile(
        r"^>>\s*\[(\d+)\]\s*>\s*(\d+)\s*/\s*(\d+)\s*-\s*(.+)$"
    )

    # Pattern for dialog lines: :: Character : inflection : dialog text
    DIALOG_PATTERN = re.compile(r"^::\s*(.+?)\s*:\s*(.+?)\s*:\s*(.+)$")

    # Pattern for summary: == summary text
    SUMMARY_PATTERN = re.compile(r"^==\s*(.+)$")

    def parse(self, text: str) -> WaveLangScript:
        """
        Parse a complete WaveLang script.

        Args:
            text: Raw WaveLang script text

        Returns:
            Parsed WaveLangScript model
        """
        lines = text.strip().split("\n")
        scenes: list[Scene] = []
        current_scene: Scene | None = None
        summary: str | None = None
        errors: list[ParseError] = []
        global_line_number = 0  # Track line number for TTS file naming

        for line_num, line in enumerate(lines, start=1):
            original_line = line
            line = line.strip()

            if not line:
                continue

            # Check for scene header
            header_match = self.SCENE_HEADER_PATTERN.match(line)
            if header_match:
                # Save previous scene
                if current_scene:
                    scenes.append(current_scene)

                # Parse character list
                char_text = header_match.group(4)
                characters = [c.strip() for c in char_text.split(",") if c.strip()]

                header = SceneHeader(
                    shot_id=int(header_match.group(1)),
                    character_count=int(header_match.group(2)),
                    max_characters=int(header_match.group(3)),
                    characters=characters,
                )
                current_scene = Scene(header=header, dialog=[])
                continue

            # Check for dialog
            dialog_match = self.DIALOG_PATTERN.match(line)
            if dialog_match:
                global_line_number += 1

                if not current_scene:
                    errors.append(
                        ParseError(
                            line_number=line_num,
                            message="Dialog line before scene header",
                            raw_line=original_line,
                        )
                    )
                    continue

                dialog = DialogLine(
                    character=dialog_match.group(1).strip(),
                    inflection=dialog_match.group(2).strip(),
                    text=dialog_match.group(3).strip(),
                    line_number=global_line_number,
                )
                current_scene.dialog.append(dialog)
                continue

            # Check for summary
            summary_match = self.SUMMARY_PATTERN.match(line)
            if summary_match:
                summary = summary_match.group(1).strip()
                continue

            # Unknown line format - skip comments and empty-ish lines
            if line and not line.startswith("#") and not line.startswith("```"):
                errors.append(
                    ParseError(
                        line_number=line_num,
                        message="Unrecognized line format",
                        raw_line=original_line,
                    )
                )

        # Add final scene
        if current_scene:
            scenes.append(current_scene)

        # Log warnings for parse errors
        if errors:
            for error in errors:
                logger.warning(
                    "parse_warning",
                    line=error.line_number,
                    message=error.message,
                    content=error.raw_line[:50] + "..." if len(error.raw_line) > 50 else error.raw_line,
                )

        return WaveLangScript(
            scenes=scenes,
            summary=summary,
            raw_text=text,
        )

    def extract_plot_and_script(self, response: str) -> tuple[str, str]:
        """
        Extract plot and script sections from LLM response.

        Expected format:
        === PLOT ===
        title: ...
        exposition: ...
        ...

        === SCRIPT ===
        >> [1] > 3/4 - Character, Character
        ...

        Args:
            response: Raw LLM response text

        Returns:
            Tuple of (plot_text, script_text)

        Raises:
            ValueError: If sections cannot be found
        """
        # Find plot section
        plot_match = re.search(
            r"===\s*PLOT\s*===\s*\n(.*?)(?=\n===\s*SCRIPT\s*===|\Z)",
            response,
            re.DOTALL | re.IGNORECASE,
        )

        # Find script section
        script_match = re.search(
            r"===\s*SCRIPT\s*===\s*\n(.*)",
            response,
            re.DOTALL | re.IGNORECASE,
        )

        if not plot_match:
            raise ValueError("Could not find === PLOT === section in response")

        if not script_match:
            raise ValueError("Could not find === SCRIPT === section in response")

        plot_text = plot_match.group(1).strip()
        script_text = script_match.group(1).strip()

        return plot_text, script_text


class PlotParser:
    """Parser for episode plot structure."""

    BEAT_PATTERNS = {
        "title": re.compile(r"title\s*:\s*(.+)", re.IGNORECASE),
        "exposition": re.compile(r"exposition\s*:\s*(.+?)(?=\n\w+\s*:|$)", re.IGNORECASE | re.DOTALL),
        "rising_action": re.compile(r"rising[_\s]?action\s*:\s*(.+?)(?=\n\w+\s*:|$)", re.IGNORECASE | re.DOTALL),
        "climax": re.compile(r"climax\s*:\s*(.+?)(?=\n\w+\s*:|$)", re.IGNORECASE | re.DOTALL),
        "falling_action": re.compile(r"falling[_\s]?action\s*:\s*(.+?)(?=\n\w+\s*:|$)", re.IGNORECASE | re.DOTALL),
        "resolution": re.compile(r"resolution\s*:\s*(.+?)(?=\n\w+\s*:|$)", re.IGNORECASE | re.DOTALL),
    }

    def parse(self, text: str) -> dict[str, str]:
        """
        Parse plot text into structured beats.

        Args:
            text: Raw plot text

        Returns:
            Dictionary with keys: title, exposition, rising_action, climax,
            falling_action, resolution
        """
        result: dict[str, str] = {}

        for beat_name, pattern in self.BEAT_PATTERNS.items():
            match = pattern.search(text)
            if match:
                result[beat_name] = match.group(1).strip()

        return result
