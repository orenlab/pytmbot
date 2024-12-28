#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import sys

from pytmbot import pytmbot_instance, logs


def main():
    """
    Main function to start the pyTMBot instance.
    """
    try:
        manager = pytmbot_instance.PyTMBot()
        manager.launch_bot()
    except Exception as e:
        logs.bot_logger.critical(f"Failed to start the bot instance: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
