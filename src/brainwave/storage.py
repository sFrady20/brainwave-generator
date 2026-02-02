"""Cloud storage providers for completed episodes."""

import json
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import structlog

from brainwave.config import StorageConfig

logger = structlog.get_logger()


class StorageProvider(ABC):
    """Abstract base class for storage providers."""

    @abstractmethod
    def upload_episode(self, local_dir: Path, episode_id: str) -> str:
        """
        Upload a complete episode directory to storage.

        Args:
            local_dir: Local directory containing episode files
            episode_id: Unique episode identifier

        Returns:
            Remote path/URL to the uploaded episode
        """
        pass

    @abstractmethod
    def download_episode(self, episode_id: str, local_dir: Path) -> Path:
        """
        Download an episode from storage to local directory.

        Args:
            episode_id: Unique episode identifier
            local_dir: Local directory to download to

        Returns:
            Path to the downloaded episode directory
        """
        pass

    @abstractmethod
    def list_episodes(self) -> list[str]:
        """
        List all episode IDs in storage.

        Returns:
            List of episode IDs
        """
        pass

    @abstractmethod
    def episode_exists(self, episode_id: str) -> bool:
        """
        Check if an episode exists in storage.

        Args:
            episode_id: Unique episode identifier

        Returns:
            True if episode exists
        """
        pass

    @abstractmethod
    def delete_episode(self, episode_id: str) -> bool:
        """
        Delete an episode from storage.

        Args:
            episode_id: Unique episode identifier

        Returns:
            True if deleted successfully
        """
        pass

    @abstractmethod
    def get_episode_meta(self, episode_id: str) -> dict[str, Any] | None:
        """
        Get episode metadata without downloading full episode.

        Args:
            episode_id: Unique episode identifier

        Returns:
            Metadata dict or None if not found
        """
        pass


class LocalStorageProvider(StorageProvider):
    """Local filesystem storage (for development/testing)."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def upload_episode(self, local_dir: Path, episode_id: str) -> str:
        """Copy episode to local storage directory."""
        dest_dir = self.base_dir / episode_id

        if dest_dir.exists():
            shutil.rmtree(dest_dir)

        shutil.copytree(local_dir, dest_dir)
        logger.info("episode_uploaded_local", episode_id=episode_id, path=str(dest_dir))
        return str(dest_dir)

    def download_episode(self, episode_id: str, local_dir: Path) -> Path:
        """Copy episode from storage to local directory."""
        source_dir = self.base_dir / episode_id
        dest_dir = local_dir / episode_id

        if not source_dir.exists():
            raise FileNotFoundError(f"Episode not found: {episode_id}")

        if dest_dir.exists():
            shutil.rmtree(dest_dir)

        shutil.copytree(source_dir, dest_dir)
        return dest_dir

    def list_episodes(self) -> list[str]:
        """List all episode IDs in storage."""
        episodes = []
        for path in self.base_dir.iterdir():
            if path.is_dir() and (path / "meta.json").exists():
                episodes.append(path.name)
        return sorted(episodes)

    def episode_exists(self, episode_id: str) -> bool:
        """Check if episode exists."""
        return (self.base_dir / episode_id / "meta.json").exists()

    def delete_episode(self, episode_id: str) -> bool:
        """Delete episode from storage."""
        episode_dir = self.base_dir / episode_id
        if episode_dir.exists():
            shutil.rmtree(episode_dir)
            logger.info("episode_deleted_local", episode_id=episode_id)
            return True
        return False

    def get_episode_meta(self, episode_id: str) -> dict[str, Any] | None:
        """Get episode metadata."""
        meta_path = self.base_dir / episode_id / "meta.json"
        if meta_path.exists():
            with open(meta_path) as f:
                return json.load(f)
        return None


class S3StorageProvider(StorageProvider):
    """S3-compatible storage (AWS S3, Cloudflare R2, MinIO, etc.)."""

    def __init__(self, config: StorageConfig):
        self.config = config
        self.prefix = config.prefix.rstrip("/")

        # Import boto3 here to avoid hard dependency
        try:
            import boto3
        except ImportError:
            raise ImportError("boto3 is required for S3 storage. Install with: pip install boto3")

        # Build client configuration
        client_kwargs: dict[str, Any] = {
            "service_name": "s3",
            "region_name": config.region,
        }

        if config.endpoint_url:
            client_kwargs["endpoint_url"] = config.endpoint_url

        if config.access_key_id and config.secret_access_key:
            client_kwargs["aws_access_key_id"] = config.access_key_id.get_secret_value()
            client_kwargs["aws_secret_access_key"] = config.secret_access_key.get_secret_value()

        self.client = boto3.client(**client_kwargs)
        self.bucket = config.bucket

        logger.info(
            "s3_storage_initialized",
            bucket=self.bucket,
            endpoint=config.endpoint_url,
            prefix=self.prefix,
        )

    def _get_key(self, episode_id: str, filename: str) -> str:
        """Build S3 key for a file."""
        return f"{self.prefix}/{episode_id}/{filename}"

    def upload_episode(self, local_dir: Path, episode_id: str) -> str:
        """Upload episode directory to S3."""
        uploaded_count = 0

        for file_path in local_dir.rglob("*"):
            if file_path.is_file():
                relative_path = file_path.relative_to(local_dir)
                key = self._get_key(episode_id, str(relative_path).replace("\\", "/"))

                # Determine content type
                content_type = "application/octet-stream"
                if file_path.suffix == ".json":
                    content_type = "application/json"
                elif file_path.suffix == ".txt":
                    content_type = "text/plain"
                elif file_path.suffix == ".mp3":
                    content_type = "audio/mpeg"

                with open(file_path, "rb") as f:
                    self.client.put_object(
                        Bucket=self.bucket,
                        Key=key,
                        Body=f,
                        ContentType=content_type,
                    )
                uploaded_count += 1

        logger.info(
            "episode_uploaded_s3",
            episode_id=episode_id,
            files_count=uploaded_count,
            bucket=self.bucket,
        )

        return f"s3://{self.bucket}/{self.prefix}/{episode_id}/"

    def download_episode(self, episode_id: str, local_dir: Path) -> Path:
        """Download episode from S3 to local directory."""
        dest_dir = local_dir / episode_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        prefix = f"{self.prefix}/{episode_id}/"

        # List and download all objects with this prefix
        paginator = self.client.get_paginator("list_objects_v2")
        downloaded_count = 0

        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                relative_path = key[len(prefix):]

                if not relative_path:
                    continue

                local_path = dest_dir / relative_path
                local_path.parent.mkdir(parents=True, exist_ok=True)

                self.client.download_file(self.bucket, key, str(local_path))
                downloaded_count += 1

        if downloaded_count == 0:
            raise FileNotFoundError(f"Episode not found: {episode_id}")

        logger.info(
            "episode_downloaded_s3",
            episode_id=episode_id,
            files_count=downloaded_count,
        )

        return dest_dir

    def list_episodes(self) -> list[str]:
        """List all episode IDs in S3."""
        episodes = set()
        prefix = f"{self.prefix}/"

        paginator = self.client.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix, Delimiter="/"):
            for common_prefix in page.get("CommonPrefixes", []):
                # Extract episode ID from prefix like "episodes/abc-123/"
                episode_prefix = common_prefix["Prefix"]
                parts = episode_prefix.rstrip("/").split("/")
                if len(parts) >= 2:
                    episodes.add(parts[-1])

        return sorted(episodes)

    def episode_exists(self, episode_id: str) -> bool:
        """Check if episode exists in S3."""
        key = self._get_key(episode_id, "meta.json")
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except self.client.exceptions.ClientError:
            return False

    def delete_episode(self, episode_id: str) -> bool:
        """Delete episode from S3."""
        prefix = f"{self.prefix}/{episode_id}/"

        # List all objects to delete
        objects_to_delete = []
        paginator = self.client.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                objects_to_delete.append({"Key": obj["Key"]})

        if not objects_to_delete:
            return False

        # Delete in batches of 1000 (S3 limit)
        for i in range(0, len(objects_to_delete), 1000):
            batch = objects_to_delete[i : i + 1000]
            self.client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": batch},
            )

        logger.info(
            "episode_deleted_s3",
            episode_id=episode_id,
            objects_count=len(objects_to_delete),
        )

        return True

    def get_episode_meta(self, episode_id: str) -> dict[str, Any] | None:
        """Get episode metadata from S3."""
        key = self._get_key(episode_id, "meta.json")
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            return json.loads(response["Body"].read().decode("utf-8"))
        except self.client.exceptions.NoSuchKey:
            return None
        except Exception:
            return None


def create_storage_provider(config: StorageConfig, local_fallback_dir: Path) -> StorageProvider:
    """
    Create the appropriate storage provider based on configuration.

    Args:
        config: Storage configuration
        local_fallback_dir: Directory to use for local storage

    Returns:
        Configured storage provider
    """
    if config.provider == "local":
        return LocalStorageProvider(local_fallback_dir)
    elif config.provider in ("s3", "r2"):
        return S3StorageProvider(config)
    else:
        raise ValueError(f"Unknown storage provider: {config.provider}")
