"""WaveLang script data models."""

from pydantic import BaseModel, Field


class DialogLine(BaseModel):
    """A single line of dialog in WaveLang format."""

    character: str
    inflection: str
    text: str
    line_number: int  # Original line number in script (for TTS file naming)

    class Config:
        frozen = True


class SceneHeader(BaseModel):
    """Scene header parsed from WaveLang format."""

    shot_id: int
    character_count: int
    max_characters: int
    characters: list[str]

    class Config:
        frozen = True


class Scene(BaseModel):
    """A complete scene with header and dialog lines."""

    header: SceneHeader
    dialog: list[DialogLine] = Field(default_factory=list)

    @property
    def character_names(self) -> list[str]:
        """Get list of character names in this scene."""
        return self.header.characters

    @property
    def dialog_count(self) -> int:
        """Get number of dialog lines in this scene."""
        return len(self.dialog)


class WaveLangScript(BaseModel):
    """Complete parsed WaveLang script."""

    scenes: list[Scene] = Field(default_factory=list)
    summary: str | None = None  # The == summary section (if present)
    raw_text: str = ""  # Original text for reference

    @property
    def all_dialog_lines(self) -> list[DialogLine]:
        """Flatten all dialog lines across all scenes."""
        return [line for scene in self.scenes for line in scene.dialog]

    @property
    def scene_count(self) -> int:
        """Get total number of scenes."""
        return len(self.scenes)

    @property
    def dialog_count(self) -> int:
        """Get total number of dialog lines."""
        return sum(scene.dialog_count for scene in self.scenes)

    @property
    def all_characters(self) -> set[str]:
        """Get set of all unique characters appearing in the script."""
        characters: set[str] = set()
        for scene in self.scenes:
            characters.update(scene.header.characters)
        return characters
