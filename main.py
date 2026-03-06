import sys
import logging

from args import cmdline_args
from bot import RedditBot, GhostLogger


def setup_error_logger():
    logger = logging.getLogger("reddit-bot")
    logger.setLevel(logging.ERROR)
    logger.addHandler(logging.StreamHandler())
    logger.addHandler(logging.FileHandler(".log"))
    formatter = logging.Formatter(
        "\033[91m[ERROR!]\033[0m %(asctime)s \033[95m%(message)s\033[0m"
    )
    logger.handlers[0].setFormatter(formatter)
    return logger


def read_file_lines(path, label, logger):
    try:
        with open(path, "r") as f:
            return [line for line in f.readlines() if line.strip()]
    except FileNotFoundError:
        logger.error(f"{label} file not found: {path}")
        sys.exit(1)


def main():
    args = cmdline_args()

    logger = GhostLogger()
    if args["verbose"]:
        logger = setup_error_logger()

    if not args["accounts"]:
        logger.error("No accounts file provided. Use -h or --help for help.")
        sys.exit(1)

    if not args["links"]:
        logger.error("No links file provided. Use -h or --help for help.")
        sys.exit(1)

    accounts = read_file_lines(args["accounts"], "Accounts", logger)
    links = read_file_lines(args["links"], "Links", logger)

    with RedditBot(verbose=args["verbose"]) as bot:
        for acc in accounts:
            username, password = acc.strip().split("|", maxsplit=1)
            try:
                bot.login(username, password)
            except RuntimeError:
                logger.error(f"Invalid account {username}")
                continue

            for entry in links:
                contents = entry.strip().split("|")
                link = contents[0]
                action = contents[1]

                if action == "upvote":
                    bot.vote(link, True)
                elif action == "downvote":
                    bot.vote(link, False)
                elif action == "comment":
                    bot.comment(link, contents[2])
                elif action in ("join", "leave"):
                    bot.join_community(link, action == "join")


if __name__ == "__main__":
    main()
