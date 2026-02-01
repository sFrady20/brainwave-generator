"""Script validation against character and shot constraints."""

from dataclasses import dataclass, field

from brainwave.models.characters import CharacterRegistry, ShotRegistry
from brainwave.models.script import WaveLangScript


@dataclass
class ValidationError:
    """A single validation error."""

    code: str
    message: str
    scene_index: int | None = None
    line_number: int | None = None
    severity: str = "error"  # "error" or "warning"


@dataclass
class ValidationResult:
    """Result of script validation."""

    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Check if validation passed (no errors, warnings are OK)."""
        return len(self.errors) == 0

    @property
    def error_count(self) -> int:
        """Get total error count."""
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        """Get total warning count."""
        return len(self.warnings)

    def add_error(
        self,
        code: str,
        message: str,
        scene_index: int | None = None,
        line_number: int | None = None,
    ) -> None:
        """Add an error to the result."""
        self.errors.append(
            ValidationError(
                code=code,
                message=message,
                scene_index=scene_index,
                line_number=line_number,
                severity="error",
            )
        )

    def add_warning(
        self,
        code: str,
        message: str,
        scene_index: int | None = None,
        line_number: int | None = None,
    ) -> None:
        """Add a warning to the result."""
        self.warnings.append(
            ValidationError(
                code=code,
                message=message,
                scene_index=scene_index,
                line_number=line_number,
                severity="warning",
            )
        )


class ScriptValidator:
    """Validates WaveLang scripts against character and shot constraints."""

    def __init__(
        self,
        characters: CharacterRegistry,
        shots: ShotRegistry,
    ):
        self.characters = characters
        self.shots = shots

    def validate(self, script: WaveLangScript) -> ValidationResult:
        """
        Validate a complete script.

        Checks:
        - Shot IDs exist
        - Character counts don't exceed shot limits
        - Characters exist in registry
        - Gender restrictions are respected
        - Dialog characters are in scene

        Args:
            script: Parsed WaveLang script

        Returns:
            ValidationResult with errors and warnings
        """
        result = ValidationResult()

        if not script.scenes:
            result.add_warning("EMPTY_SCRIPT", "Script has no scenes")
            return result

        for scene_idx, scene in enumerate(script.scenes):
            self._validate_scene(scene_idx, scene, result)

        return result

    def _validate_scene(
        self,
        scene_idx: int,
        scene,
        result: ValidationResult,
    ) -> None:
        """Validate a single scene."""
        header = scene.header

        # Check shot exists
        shot = self.shots.get_by_id(header.shot_id)
        if not shot:
            result.add_error(
                "INVALID_SHOT",
                f"Shot ID {header.shot_id} does not exist",
                scene_index=scene_idx,
            )
            return  # Can't validate further without shot info

        # Check character count vs max
        if len(header.characters) > shot.max_characters:
            result.add_error(
                "TOO_MANY_CHARACTERS",
                f"Scene has {len(header.characters)} characters, shot {header.shot_id} allows max {shot.max_characters}",
                scene_index=scene_idx,
            )

        # Check character count matches header
        if header.character_count != len(header.characters):
            result.add_warning(
                "CHARACTER_COUNT_MISMATCH",
                f"Header says {header.character_count} characters but lists {len(header.characters)}",
                scene_index=scene_idx,
            )

        # Validate each character in scene
        for char_name in header.characters:
            char = self.characters.find_by_name(char_name)

            if not char:
                result.add_warning(
                    "UNKNOWN_CHARACTER",
                    f"Character '{char_name}' not found in registry",
                    scene_index=scene_idx,
                )
                continue

            # Check gender restriction
            if shot.gender_restriction and char.gender != shot.gender_restriction:
                result.add_error(
                    "GENDER_RESTRICTION",
                    f"Shot {shot.id} requires {shot.gender_restriction} characters, "
                    f"but '{char_name}' is {char.gender}",
                    scene_index=scene_idx,
                )

        # Validate dialog
        scene_char_names = {c.lower() for c in header.characters}

        for dialog in scene.dialog:
            # Check if speaking character is in scene
            dialog_char = self.characters.find_by_name(dialog.character)

            if dialog_char:
                # Check if character is in this scene
                if dialog_char.id.lower() not in scene_char_names:
                    # Try to match by the exact name used
                    if dialog.character.lower() not in scene_char_names:
                        result.add_warning(
                            "DIALOG_CHARACTER_NOT_IN_SCENE",
                            f"Character '{dialog.character}' has dialog but may not be in scene",
                            scene_index=scene_idx,
                            line_number=dialog.line_number,
                        )
            else:
                result.add_warning(
                    "UNKNOWN_DIALOG_CHARACTER",
                    f"Dialog character '{dialog.character}' not found in registry",
                    scene_index=scene_idx,
                    line_number=dialog.line_number,
                )

            # Check for empty dialog
            if not dialog.text.strip():
                result.add_error(
                    "EMPTY_DIALOG",
                    f"Empty dialog text for character '{dialog.character}'",
                    scene_index=scene_idx,
                    line_number=dialog.line_number,
                )

    def validate_and_summarize(self, script: WaveLangScript) -> str:
        """
        Validate and return a human-readable summary.

        Args:
            script: Parsed WaveLang script

        Returns:
            Summary string with validation results
        """
        result = self.validate(script)

        lines = []
        lines.append(f"Validation: {'PASSED' if result.is_valid else 'FAILED'}")
        lines.append(f"  Scenes: {script.scene_count}")
        lines.append(f"  Dialog lines: {script.dialog_count}")
        lines.append(f"  Errors: {result.error_count}")
        lines.append(f"  Warnings: {result.warning_count}")

        if result.errors:
            lines.append("\nErrors:")
            for err in result.errors:
                scene_info = f"Scene {err.scene_index}" if err.scene_index is not None else ""
                line_info = f" Line {err.line_number}" if err.line_number is not None else ""
                lines.append(f"  [{err.code}] {scene_info}{line_info}: {err.message}")

        if result.warnings:
            lines.append("\nWarnings:")
            for warn in result.warnings[:5]:  # Limit to first 5
                scene_info = f"Scene {warn.scene_index}" if warn.scene_index is not None else ""
                line_info = f" Line {warn.line_number}" if warn.line_number is not None else ""
                lines.append(f"  [{warn.code}] {scene_info}{line_info}: {warn.message}")
            if len(result.warnings) > 5:
                lines.append(f"  ... and {len(result.warnings) - 5} more warnings")

        return "\n".join(lines)
