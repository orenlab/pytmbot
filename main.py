#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""


def main():
    """
    Main function to start the Telegram bot instance.
    """
    from pytmbot import pytmbot_instance

    try:
        pytmbot_instance.start_bot_instance()
    except Exception as e:
        print("Failed to start the bot instance" + str(e))
        exit(1)


if __name__ == "__main__":
    main()
