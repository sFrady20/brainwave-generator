"""OpenAI TTS provider."""

from pathlib import Path

import structlog
from openai import OpenAI

from brainwave.tts.base import TTSProvider, TTSResult

logger = structlog.get_logger()


class OpenAITTSProvider(TTSProvider):
    """OpenAI TTS API provider."""

    # Available OpenAI TTS voices
    VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        model: str = "tts-1",
    ):
        """
        Initialize OpenAI TTS provider.

        Args:
            api_key: OpenAI API key
            base_url: Optional base URL override
            model: TTS model to use (tts-1 or tts-1-hd)
        """
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    @property
    def name(self) -> str:
        return "openai"

    @property
    def supported_voices(self) -> list[str]:
        return self.VOICES

    def synthesize(
        self,
        text: str,
        voice: str,
        output_path: Path,
    ) -> TTSResult:
        """
        Synthesize speech using OpenAI TTS API.

        Args:
            text: Text to synthesize
            voice: OpenAI voice ID (alloy, echo, fable, onyx, nova, shimmer)
            output_path: Where to save the MP3 file

        Returns:
            TTSResult with path
        """
        # Validate voice
        if voice.lower() not in [v.lower() for v in self.VOICES]:
            logger.warning("unknown_voice", voice=voice, using="alloy")
            voice = "alloy"

        try:
            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Call OpenAI TTS API
            response = self.client.audio.speech.create(
                model=self.model,
                voice=voice.lower(),  # type: ignore
                input=text,
                response_format="mp3",
            )

            # Write audio to file
            response.stream_to_file(output_path)

            logger.debug("tts_synthesized", voice=voice, path=str(output_path))

            return TTSResult(audio_path=output_path)

        except Exception as e:
            logger.error("tts_failed", voice=voice, error=str(e))
            return TTSResult(audio_path=output_path, error=str(e))
