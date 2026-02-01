"""Configuration management for brainwave."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseModel):
    """LLM configuration."""

    provider: Literal["openai", "anthropic", "azure"] = "openai"
    model: str = "gpt-4o"
    api_key: SecretStr | None = None
    base_url: str | None = None
    temperature: float = 0.9
    max_tokens: int = 16000
    timeout: int = 120


class TTSConfig(BaseModel):
    """TTS configuration."""

    provider: Literal["openai", "elevenlabs", "local", "mock"] = "mock"
    api_key: SecretStr | None = None
    base_url: str | None = None
    voice_mapping_file: Path | None = None


class PathsConfig(BaseModel):
    """Paths configuration."""

    scenes_dir: Path = Path("scenes")
    data_dir: Path = Path("data")
    templates_dir: Path = Path("templates")
    placeholders_dir: Path = Path("placeholders")


class AppConfig(BaseSettings):
    """Complete application configuration."""

    model_config = SettingsConfigDict(
        env_prefix="BRAINWAVE_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm: LLMConfig = Field(default_factory=LLMConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    debug: bool = False
    log_level: str = "INFO"

    # Direct environment variable overrides
    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    elevenlabs_api_key: SecretStr | None = Field(default=None, alias="ELEVENLABS_API_KEY")


def load_config(config_path: Path | None = None, root_dir: Path | None = None) -> AppConfig:
    """
    Load configuration from file and environment variables.

    Priority (highest to lowest):
    1. Environment variables
    2. Config file
    3. Defaults

    Args:
        config_path: Optional path to config.yaml file
        root_dir: Root directory for resolving relative paths

    Returns:
        Complete AppConfig instance
    """
    config_dict: dict = {}

    # Try to find config file
    if config_path is None:
        for candidate in ["config.yaml", "config.yml"]:
            if Path(candidate).exists():
                config_path = Path(candidate)
                break

    # Load from file if found
    if config_path and config_path.exists():
        with open(config_path) as f:
            config_dict = yaml.safe_load(f) or {}

    # Build config (env vars are loaded automatically by pydantic-settings)
    config = AppConfig(**config_dict)

    # Apply API key overrides
    if config.openai_api_key and not config.llm.api_key:
        config.llm.api_key = config.openai_api_key

    if config.elevenlabs_api_key and not config.tts.api_key:
        if config.tts.provider == "elevenlabs":
            config.tts.api_key = config.elevenlabs_api_key

    # Resolve relative paths
    if root_dir:
        config.paths.scenes_dir = root_dir / config.paths.scenes_dir
        config.paths.data_dir = root_dir / config.paths.data_dir
        config.paths.templates_dir = root_dir / config.paths.templates_dir
        config.paths.placeholders_dir = root_dir / config.paths.placeholders_dir

    return config
