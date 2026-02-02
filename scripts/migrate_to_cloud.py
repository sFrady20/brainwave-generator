#!/usr/bin/env python3
"""Migrate existing built episodes to cloud storage.

Usage:
    python scripts/migrate_to_cloud.py --dry-run  # Preview what would be migrated
    python scripts/migrate_to_cloud.py            # Actually migrate

This script:
1. Scans the scenes/ directory for existing episodes
2. Filters to only BUILT episodes (have audio files)
3. Uploads them to the configured cloud storage
4. Optionally removes local copies after upload
"""

import argparse
import json
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from brainwave.config import load_config
from brainwave.models.episode import EpisodeStatus
from brainwave.storage import create_storage_provider


def find_built_episodes(scenes_dir: Path) -> list[tuple[str, dict]]:
    """Find all built episodes in the scenes directory."""
    episodes = []

    if not scenes_dir.exists():
        return episodes

    for episode_dir in scenes_dir.iterdir():
        if not episode_dir.is_dir():
            continue

        meta_path = episode_dir / "meta.json"
        if not meta_path.exists():
            continue

        try:
            with open(meta_path) as f:
                meta = json.load(f)

            status = meta.get("status", "")

            # Check if episode is built (has audio)
            assets_dir = episode_dir / "assets" / "sfx"
            has_audio = assets_dir.exists() and any(assets_dir.glob("*.mp3"))

            # Include if status is BUILT or if it has audio files
            if status in ("built", "script_generated") and has_audio:
                episodes.append((episode_dir.name, meta))
            elif has_audio:
                # Has audio but unexpected status - still include
                episodes.append((episode_dir.name, meta))

        except Exception as e:
            print(f"Warning: Could not read {episode_dir.name}: {e}")

    return episodes


def count_files(directory: Path) -> int:
    """Count files in a directory recursively."""
    return sum(1 for _ in directory.rglob("*") if _.is_file())


def main():
    parser = argparse.ArgumentParser(description="Migrate built episodes to cloud storage")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without actually doing it",
    )
    parser.add_argument(
        "--keep-local",
        action="store_true",
        help="Keep local copies after uploading (don't delete)",
    )
    parser.add_argument(
        "--scenes-dir",
        type=Path,
        default=Path("scenes"),
        help="Path to scenes directory (default: scenes/)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config file",
    )

    args = parser.parse_args()

    # Load configuration
    root_dir = Path(__file__).parent.parent
    config = load_config(args.config, root_dir)

    scenes_dir = args.scenes_dir
    if not scenes_dir.is_absolute():
        scenes_dir = root_dir / scenes_dir

    print(f"Scanning {scenes_dir} for built episodes...")
    episodes = find_built_episodes(scenes_dir)

    if not episodes:
        print("No built episodes found to migrate.")
        return

    print(f"\nFound {len(episodes)} built episode(s):")
    print("-" * 60)

    for episode_id, meta in episodes:
        title = meta.get("title", "Untitled")
        status = meta.get("status", "unknown")
        episode_dir = scenes_dir / episode_id
        file_count = count_files(episode_dir)
        print(f"  {episode_id[:8]}...  {title[:30]:<30}  ({status}, {file_count} files)")

    print("-" * 60)

    if args.dry_run:
        print("\n[DRY RUN] No changes made. Remove --dry-run to actually migrate.")
        return

    # Confirm
    response = input(f"\nMigrate {len(episodes)} episode(s) to {config.storage.provider}? [y/N] ")
    if response.lower() != "y":
        print("Aborted.")
        return

    # Create storage provider
    storage = create_storage_provider(config.storage, config.paths.scenes_dir)

    # Migrate each episode
    success_count = 0
    for episode_id, meta in episodes:
        episode_dir = scenes_dir / episode_id
        title = meta.get("title", "Untitled")

        print(f"\nMigrating: {episode_id[:8]}... ({title[:30]})")

        try:
            # Check if already exists in cloud
            if storage.episode_exists(episode_id):
                print(f"  Already exists in cloud, skipping upload")
            else:
                # Upload
                remote_path = storage.upload_episode(episode_dir, episode_id)
                print(f"  Uploaded to: {remote_path}")

            # Update meta to mark as completed
            meta["status"] = "completed"
            meta_path = episode_dir / "meta.json"
            with open(meta_path, "w") as f:
                json.dump(meta, f, indent=2)

            # Optionally remove local copy
            if not args.keep_local:
                import shutil
                shutil.rmtree(episode_dir)
                print(f"  Removed local copy")

            success_count += 1

        except Exception as e:
            print(f"  ERROR: {e}")

    print(f"\n{'=' * 60}")
    print(f"Migration complete: {success_count}/{len(episodes)} episodes migrated")

    if args.keep_local:
        print("Local copies were preserved (--keep-local)")


if __name__ == "__main__":
    main()
