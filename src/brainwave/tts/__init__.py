"""Text-to-speech provider system."""

from brainwave.tts.base import TTSProvider, TTSResult
from brainwave.tts.mock import MockTTSProvider
from brainwave.tts.narakeet import NarakeetTTSProvider
from brainwave.tts.openai import OpenAITTSProvider

__all__ = [
    "TTSProvider",
    "TTSResult",
    "MockTTSProvider",
    "NarakeetTTSProvider",
    "OpenAITTSProvider",
]
