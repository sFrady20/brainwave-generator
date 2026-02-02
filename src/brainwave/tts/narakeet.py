"""Narakeet TTS provider."""

from pathlib import Path

import httpx
import structlog

from brainwave.tts.base import TTSProvider, TTSResult

logger = structlog.get_logger()


class NarakeetTTSProvider(TTSProvider):
    """Narakeet TTS API provider."""

    API_URL = "https://api.narakeet.com/text-to-speech/mp3"

    # Common Narakeet voices (there are many more available)
    # See: https://www.narakeet.com/languages/
    VOICES = [
        # English US
        "rodney", "linda", "mike", "karen", "tom", "lisa",
        # English UK
        "brian", "emma",
        # English AU
        "bruce", "jodie",
        # Other accents
        "cillian", "mia", "shilpa", "obinna",
    ]

    def __init__(
        self,
        api_key: str,
        timeout: int = 60,
    ):
        """
        Initialize Narakeet TTS provider.

        Args:
            api_key: Narakeet API key
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "narakeet"

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
        Synthesize speech using Narakeet TTS API.

        Args:
            text: Text to synthesize
            voice: Narakeet voice name
            output_path: Where to save the MP3 file

        Returns:
            TTSResult with path
        """
        try:
            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Build request
            url = f"{self.API_URL}?voice={voice}"
            headers = {
                "Accept": "application/octet-stream",
                "Content-Type": "text/plain",
                "x-api-key": self.api_key,
            }

            # Make request
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    url,
                    headers=headers,
                    content=text.encode("utf-8"),
                )
                response.raise_for_status()

                # Write audio to file
                with open(output_path, "wb") as f:
                    f.write(response.content)

            logger.debug("tts_synthesized", voice=voice, path=str(output_path))

            return TTSResult(audio_path=output_path)

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text[:100]}"
            logger.error("tts_failed", voice=voice, error=error_msg)
            return TTSResult(audio_path=output_path, error=error_msg)

        except Exception as e:
            logger.error("tts_failed", voice=voice, error=str(e))
            return TTSResult(audio_path=output_path, error=str(e))
