#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from pytmbot.utils.utilities import parse_cli_args, generate_random_auth_salt

if __name__ == "__main__":
    cli_args = parse_cli_args()
    if cli_args.salt is True:
        print("Your salt: " + generate_random_auth_salt())
        exit(0)
    else:
        from pytmbot import pytmbot_instance

        pytmbot_instance.start_bot_instance()
