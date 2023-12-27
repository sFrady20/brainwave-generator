import argparse
from episode import Episode
import os
import paths

parser = argparse.ArgumentParser(description="Echo a string")
parser.add_argument(
    "-i",
    "--interactive",
    action="store_true",
    default=False,
    help="interactive generation",
)

subparsers = parser.add_subparsers(
    title="subcommands", description="valid subcommands", dest="subcommand"
)

# main entry for live streaming episodes
run_parser = subparsers.add_parser("run")
run_parser.add_argument(
    "-n",
    "--number",
    type=int,
    default=0,
    help="amount of episodes to generate, leave blank for infinite",
)
run_parser.add_argument("--mock", action="store_true", help="use fake narakeet sounds")

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
generate_parser.add_argument(
    "-i", "--interactive", action="store_true", help="force rebuild"
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
build_parser.add_argument("-f", "--force", action="store_true", help="force rebuild")


# Parse the command line arguments
args = parser.parse_args()

# Check which subcommand was used and call the appropriate function
if args.subcommand == "run":
    runs = 0
    while True:
        episode = Episode()
        episode.generate(interactive=False)
        episode.build(mock=args.mock)

        # quit after n episodes if number arg given
        runs += 1
        if args.number > 0 and runs >= args.number:
            break

if args.subcommand == "episode":
    if args.episode_command == "generate":
        episode_id = args.episode_id

        episode = Episode(episode_id)
        episode.generate(interactive=args.interactive)

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
        episode.build(mock=args.mock, force=args.force)
