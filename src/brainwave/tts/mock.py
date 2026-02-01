"""Mock TTS provider for testing."""

import shutil
from pathlib import Path

import structlog

from brainwave.tts.base import TTSProvider, TTSResult

logger = structlog.get_logger()


class MockTTSProvider(TTSProvider):
    """
    Mock TTS provider that copies placeholder audio files.

    Useful for testing without making actual API calls or
    for development when TTS is not yet configured.
    """

    def __init__(self, placeholders_dir: Path):
        """
        Initialize mock TTS provider.

        Args:
            placeholders_dir: Directory containing placeholder MP3 files
                             (e.g., Rodney.mp3, Karen.mp3, etc.)
        """
        self.placeholders_dir = placeholders_dir
        self._voices: list[str] = []

        # Discover available placeholder voices
        if placeholders_dir.exists():
            self._voices = [
                p.stem for p in placeholders_dir.glob("*.mp3")
            ]

    @property
    def name(self) -> str:
        return "mock"

    @property
    def supported_voices(self) -> list[str]:
        return self._voices

    def synthesize(
        self,
        text: str,
        voice: str,
        output_path: Path,
    ) -> TTSResult:
        """
        Copy a placeholder audio file to simulate TTS.

        Args:
            text: Text (ignored, just for interface compatibility)
            voice: Voice ID (name of placeholder file without extension)
            output_path: Where to copy the placeholder file

        Returns:
            TTSResult with path
        """
        # Find placeholder file
        placeholder_path = self.placeholders_dir / f"{voice}.mp3"

        if not placeholder_path.exists():
            # Try to find any placeholder as fallback
            fallback = list(self.placeholders_dir.glob("*.mp3"))
            if fallback:
                placeholder_path = fallback[0]
                logger.warning(
                    "voice_not_found",
                    voice=voice,
                    using=placeholder_path.stem,
                )
            else:
                return TTSResult(
                    audio_path=output_path,
                    error=f"No placeholder files found in {self.placeholders_dir}",
                )

        try:
            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Copy placeholder to output
            shutil.copy(placeholder_path, output_path)

            logger.debug(
                "mock_tts_copied",
                voice=voice,
                source=str(placeholder_path),
                dest=str(output_path),
            )

            return TTSResult(audio_path=output_path)

        except Exception as e:
            logger.error("mock_tts_failed", error=str(e))
            return TTSResult(audio_path=output_path, error=str(e))
