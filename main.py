#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

if __name__ == "__main__":
    from pytmbot import pytmbot_instance

    pytmbot_instance.start_bot_instance()
