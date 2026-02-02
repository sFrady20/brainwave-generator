"""Character and shot data models."""

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class Character(BaseModel):
    """Represents a character in the show."""

    id: str
    full_name: str
    description: str
    gender: Literal["male", "female"]
    quirks: str = ""  # Speech patterns and personality quirks for dialog writing
    patterns: list[str] = Field(default_factory=list)  # Regex patterns for matching
    voice_mappings: dict[str, str] = Field(default_factory=dict)  # provider -> voice

    class Config:
        frozen = True

    def matches_name(self, name: str) -> bool:
        """Check if the given name matches this character."""
        name_lower = name.lower().strip()
        # Check exact ID match first
        if name_lower == self.id.lower():
            return True
        # Check patterns
        for pattern in self.patterns:
            if re.search(pattern, name_lower, re.IGNORECASE):
                return True
        return False

    def get_voice(self, provider: str) -> str | None:
        """Get the voice ID for the given TTS provider."""
        return self.voice_mappings.get(provider)


class Shot(BaseModel):
    """Represents a camera shot in the Unity application."""

    id: int
    description: str
    max_characters: int
    gender_restriction: Literal["male", "female"] | None = None

    class Config:
        frozen = True


class CharacterRegistry(BaseModel):
    """Registry of all available characters."""

    characters: list[Character] = Field(default_factory=list)

    def find_by_name(self, name: str) -> Character | None:
        """Find character by name using pattern matching."""
        for char in self.characters:
            if char.matches_name(name):
                return char
        return None

    def get_by_id(self, char_id: str) -> Character | None:
        """Get character by exact ID."""
        for char in self.characters:
            if char.id.lower() == char_id.lower():
                return char
        return None

    def all_ids(self) -> list[str]:
        """Get all character IDs."""
        return [char.id for char in self.characters]


class ShotRegistry(BaseModel):
    """Registry of all available shots."""

    shots: list[Shot] = Field(default_factory=list)

    def get_by_id(self, shot_id: int) -> Shot | None:
        """Get shot by ID."""
        for shot in self.shots:
            if shot.id == shot_id:
                return shot
        return None

    def all_ids(self) -> list[int]:
        """Get all shot IDs."""
        return [shot.id for shot in self.shots]


def load_characters(path: Path) -> CharacterRegistry:
    """Load character registry from YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)

    characters = [Character(**char) for char in data.get("characters", [])]
    return CharacterRegistry(characters=characters)


def load_shots(path: Path) -> ShotRegistry:
    """Load shot registry from YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)

    shots = [Shot(**shot) for shot in data.get("shots", [])]
    return ShotRegistry(shots=shots)
