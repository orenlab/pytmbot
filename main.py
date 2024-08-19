#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from pytmbot import pytmbot_instance

if __name__ == "__main__":
    pytmbot_instance.start_bot_instance()
