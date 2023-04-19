import argparse
from episode import Episode, character_map
import os
import paths

parser = argparse.ArgumentParser(description="Echo a string")
subparsers = parser.add_subparsers(
    title="subcommands", description="valid subcommands", dest="subcommand"
)

placeholder_parser = subparsers.add_parser("generate-placehoders")

episode_parser = subparsers.add_parser("episode")
episode_subparsers = episode_parser.add_subparsers(
    title="subcommands", description="valid subcommands", dest="episode_command"
)

generate_parser = episode_subparsers.add_parser(
    "generate", help="generate a new episode"
)
generate_parser.add_argument(
    "episode_id", type=str, help="the id of the episode", nargs="?", default=None
)

evaluate_parser = episode_subparsers.add_parser("evaluate", help="evaluate an episode")
evaluate_parser.add_argument("episode_id", type=str, help="the id of the episode")

build_parser = episode_subparsers.add_parser(
    "build", help="build the assets for an episode"
)
build_parser.add_argument("episode_id", type=str, help="the id of the episode")
build_parser.add_argument(
    "--mock", action="store_true", help="use fake narakeet sounds"
)


# Parse the command line arguments
args = parser.parse_args()

# Check which subcommand was used and call the appropriate function
if args.subcommand == "episode":
    if args.episode_command == "generate":
        episode_id = args.episode_id

        episode = Episode(episode_id)
        episode.generate()

    elif args.episode_command == "evaluate":
        episode_id = args.episode_id

        if not os.path.exists(os.path.join(paths.scenes_dir, episode_id)):
            raise Exception("scene not found, check the scenes folder")

        episode = Episode(episode_id)
        episode.evaluate()

    elif args.episode_command == "build":
        episode_id = args.episode_id

        if not os.path.exists(os.path.join(paths.scenes_dir, episode_id)):
            raise Exception("scene not found, check the scenes folder")

        episode = Episode(episode_id)
        episode.build(mock=args.mock)
