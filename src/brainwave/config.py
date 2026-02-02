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
    timeout: int = 120


class TTSConfig(BaseModel):
    """TTS configuration."""

    provider: Literal["openai", "elevenlabs", "narakeet", "local", "mock"] = "mock"
    api_key: SecretStr | None = None
    base_url: str | None = None
    voice_mapping_file: Path | None = None


class StorageConfig(BaseModel):
    """Cloud storage configuration for S3-compatible services."""

    provider: Literal["s3", "r2", "local"] = "local"
    bucket: str = "brainwave-episodes"
    endpoint_url: str | None = None  # For R2/MinIO - e.g., https://<account>.r2.cloudflarestorage.com
    access_key_id: SecretStr | None = None
    secret_access_key: SecretStr | None = None
    region: str = "auto"
    prefix: str = "episodes/"  # Key prefix for all uploads


class PathsConfig(BaseModel):
    """Paths configuration."""

    scenes_dir: Path = Path("scenes")  # Legacy completed scenes
    incomplete_dir: Path = Path(".incomplete")  # Work in progress
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
    storage: StorageConfig = Field(default_factory=StorageConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    debug: bool = False
    log_level: str = "INFO"

    # Direct environment variable overrides
    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    elevenlabs_api_key: SecretStr | None = Field(default=None, alias="ELEVENLABS_API_KEY")
    narakeet_api_key: SecretStr | None = Field(default=None, alias="NARAKEET_API_KEY")

    # Storage credentials from env
    aws_access_key_id: SecretStr | None = Field(default=None, alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: SecretStr | None = Field(default=None, alias="AWS_SECRET_ACCESS_KEY")
    r2_access_key_id: SecretStr | None = Field(default=None, alias="R2_ACCESS_KEY_ID")
    r2_secret_access_key: SecretStr | None = Field(default=None, alias="R2_SECRET_ACCESS_KEY")


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

    if config.narakeet_api_key and not config.tts.api_key:
        if config.tts.provider == "narakeet":
            config.tts.api_key = config.narakeet_api_key

    # Apply storage credentials
    if config.storage.provider == "r2":
        if config.r2_access_key_id and not config.storage.access_key_id:
            config.storage.access_key_id = config.r2_access_key_id
        if config.r2_secret_access_key and not config.storage.secret_access_key:
            config.storage.secret_access_key = config.r2_secret_access_key
    elif config.storage.provider == "s3":
        if config.aws_access_key_id and not config.storage.access_key_id:
            config.storage.access_key_id = config.aws_access_key_id
        if config.aws_secret_access_key and not config.storage.secret_access_key:
            config.storage.secret_access_key = config.aws_secret_access_key

    # Resolve relative paths
    if root_dir:
        config.paths.scenes_dir = root_dir / config.paths.scenes_dir
        config.paths.incomplete_dir = root_dir / config.paths.incomplete_dir
        config.paths.data_dir = root_dir / config.paths.data_dir
        config.paths.templates_dir = root_dir / config.paths.templates_dir
        config.paths.placeholders_dir = root_dir / config.paths.placeholders_dir

    return config
