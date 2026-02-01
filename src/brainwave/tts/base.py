"""Abstract base class for TTS providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TTSResult:
    """Result of a TTS synthesis operation."""

    audio_path: Path
    duration_seconds: float | None = None
    cached: bool = False
    error: str | None = None

    @property
    def success(self) -> bool:
        """Check if synthesis was successful."""
        return self.error is None and self.audio_path.exists()


class TTSProvider(ABC):
    """Abstract base class for TTS providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for configuration and logging."""
        ...

    @property
    @abstractmethod
    def supported_voices(self) -> list[str]:
        """List of supported voice IDs."""
        ...

    @abstractmethod
    def synthesize(
        self,
        text: str,
        voice: str,
        output_path: Path,
    ) -> TTSResult:
        """
        Synthesize speech from text.

        Args:
            text: Text to synthesize
            voice: Voice ID (provider-specific)
            output_path: Where to save the audio file

        Returns:
            TTSResult with path and metadata
        """
        ...

    def synthesize_batch(
        self,
        items: list[tuple[str, str, Path]],
    ) -> list[TTSResult]:
        """
        Synthesize multiple items.

        Default implementation calls synthesize() in sequence.
        Providers can override for parallel processing.

        Args:
            items: List of (text, voice, output_path) tuples

        Returns:
            List of TTSResult instances
        """
        results = []
        for text, voice, path in items:
            result = self.synthesize(text, voice, path)
            results.append(result)
        return results

    def get_voice_for_character(
        self,
        character_id: str,
        voice_mappings: dict[str, str],
    ) -> str | None:
        """
        Get the voice ID for a character.

        Args:
            character_id: Character ID (e.g., "Art", "Nia")
            voice_mappings: Mapping of character ID to voice ID

        Returns:
            Voice ID for the character, or None if not found
        """
        return voice_mappings.get(character_id)
