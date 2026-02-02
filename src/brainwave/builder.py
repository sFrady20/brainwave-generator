"""Build audio assets for episodes using TTS."""

import re
from pathlib import Path

import structlog
import yaml

from brainwave.config import AppConfig
from brainwave.models.characters import CharacterRegistry, load_characters
from brainwave.models.episode import Episode, EpisodeStatus
from brainwave.models.script import DialogLine
from brainwave.parser import WaveLangParser
from brainwave.tts.base import TTSProvider, TTSResult
from brainwave.tts.mock import MockTTSProvider
from brainwave.tts.narakeet import NarakeetTTSProvider
from brainwave.tts.openai import OpenAITTSProvider

logger = structlog.get_logger()


def get_tts_provider(config: AppConfig) -> TTSProvider:
    """
    Create a TTS provider based on configuration.

    Args:
        config: Application configuration

    Returns:
        Configured TTSProvider instance
    """
    provider_name = config.tts.provider

    if provider_name == "mock":
        return MockTTSProvider(config.paths.placeholders_dir)

    elif provider_name == "openai":
        api_key = config.tts.api_key or config.llm.api_key
        if not api_key:
            raise ValueError("OpenAI API key required for OpenAI TTS")
        return OpenAITTSProvider(
            api_key=api_key.get_secret_value(),
            base_url=config.tts.base_url,
        )

    elif provider_name == "narakeet":
        if not config.tts.api_key:
            raise ValueError("Narakeet API key required for Narakeet TTS. Set NARAKEET_API_KEY in .env")
        return NarakeetTTSProvider(
            api_key=config.tts.api_key.get_secret_value(),
        )

    elif provider_name == "local":
        from brainwave.tts.local import LocalTTSProvider
        return LocalTTSProvider()

    else:
        raise ValueError(f"Unknown TTS provider: {provider_name}")


def load_voice_mappings(config: AppConfig) -> dict[str, dict[str, str]]:
    """
    Load voice mappings from YAML file.

    Returns:
        Dictionary of provider -> character -> voice mappings
    """
    voices_path = config.paths.data_dir / "voices.yaml"

    if not voices_path.exists():
        return {}

    with open(voices_path) as f:
        return yaml.safe_load(f) or {}


class EpisodeBuilder:
    """Build audio assets for episodes."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.parser = WaveLangParser()
        self.characters = load_characters(config.paths.data_dir / "characters.yaml")
        self.voice_mappings = load_voice_mappings(config)
        self.tts_provider = get_tts_provider(config)

    def build(
        self,
        episode: Episode,
        force: bool = False,
    ) -> list[TTSResult]:
        """
        Generate TTS audio for all dialog in an episode.

        Args:
            episode: Episode to build
            force: If True, regenerate even if files exist

        Returns:
            List of TTSResult for each dialog line
        """
        if not episode.script_raw:
            raise ValueError("Episode has no script to build")

        if not episode.work_dir:
            raise ValueError("Episode has no work_dir set")

        # Create assets directory
        sfx_dir = episode.work_dir / "assets" / "sfx"
        sfx_dir.mkdir(parents=True, exist_ok=True)

        # Parse script
        script = self.parser.parse(episode.script_raw)

        # Get provider-specific voice mappings
        provider_name = self.tts_provider.name
        provider_voices = self.voice_mappings.get(provider_name, {})

        results: list[TTSResult] = []
        generated = 0
        skipped = 0

        for dialog in script.all_dialog_lines:
            output_path = sfx_dir / f"dialog-{dialog.line_number}.mp3"

            # Skip if file exists and not forcing
            if output_path.exists() and not force:
                skipped += 1
                results.append(TTSResult(audio_path=output_path, cached=True))
                continue

            # Get voice for character
            voice = self._get_voice_for_dialog(dialog, provider_voices)

            # Clean dialog text
            text = self._clean_dialog_text(dialog.text)

            if not text.strip():
                logger.warning("empty_dialog", line=dialog.line_number)
                continue

            # Synthesize
            logger.info(
                "synthesizing",
                line=dialog.line_number,
                character=dialog.character,
                voice=voice,
            )

            result = self.tts_provider.synthesize(text, voice, output_path)
            results.append(result)

            if result.success:
                generated += 1
            else:
                logger.error("synthesis_failed", line=dialog.line_number, error=result.error)

        logger.info(
            "build_complete",
            generated=generated,
            skipped=skipped,
            total=len(script.all_dialog_lines),
        )

        # Update episode status
        episode.meta.status = EpisodeStatus.BUILT
        episode.meta.tts_provider = provider_name

        return results

    def _get_voice_for_dialog(
        self,
        dialog: DialogLine,
        provider_voices: dict[str, str],
    ) -> str:
        """
        Get the voice ID for a dialog line.

        Args:
            dialog: Dialog line
            provider_voices: Provider-specific voice mappings

        Returns:
            Voice ID to use
        """
        # Try to find character in registry
        character = self.characters.find_by_name(dialog.character)

        if character:
            # First check character's own voice mappings
            voice = character.get_voice(self.tts_provider.name)
            if voice:
                return voice

            # Then check provider-level mappings
            voice = provider_voices.get(character.id)
            if voice:
                return voice

        # Try direct lookup by dialog character name
        voice = provider_voices.get(dialog.character)
        if voice:
            return voice

        # Fallback to first available voice
        if self.tts_provider.supported_voices:
            return self.tts_provider.supported_voices[0]

        return "default"

    def _clean_dialog_text(self, text: str) -> str:
        """
        Clean dialog text for TTS.

        Removes:
        - Parenthetical actions: (laughing)
        - Asterisk actions: *sighs*
        - Unknown characters

        Args:
            text: Raw dialog text

        Returns:
            Cleaned text for TTS
        """
        # Remove parenthetical actions
        text = re.sub(r"\([^)]+\)", "", text)

        # Remove asterisk actions
        text = re.sub(r"\*[^*]+\*", "", text)

        # Remove replacement character
        text = text.replace("\ufffd", "")

        # Clean up extra whitespace
        text = " ".join(text.split())

        return text.strip()
