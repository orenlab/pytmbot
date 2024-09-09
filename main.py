#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import logging
import sys

from pytmbot import pytmbot_instance


def main():
    """
    Main function to start the pyTMBot instance.
    """
    logging.basicConfig(
        level=logging.ERROR, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    try:
        manager = pytmbot_instance.PyTMBot()
        manager.start_bot_instance()
    except Exception as e:
        logging.error("Failed to start the bot instance: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
