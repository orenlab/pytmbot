#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from typing import Union

from telebot.types import Message, CallbackQuery

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session
from app.utilities.totp import TOTPGenerator


class User:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.state = None


class TOTPCodeHandler(HandlerConstructor):
    """
    Handler for sending TOTP code
    """

    def handle(self, query: Union[Message, CallbackQuery]) -> None:
        """
        Handle the 'Send TOTP code' message by sending the TOTP code to the bot.
        """

        @logged_handler_session
        def handle_totp_code_message() -> None:
            print(f"Handling TOTP code message for user {query.from_user.id}")
            # Build inline keyboard with options for QR code or entering 2FA code
            keyboard = self.keyboard.build_reply_keyboard(keyboard_type='auth_processing_keyboard')

            bot_answer = self.jinja.render_templates('send_totp_code.jinja2', context=query.from_user.first_name)

            self.bot.send_message(query.chat.id, text=bot_answer, reply_markup=keyboard)

        @logged_handler_session
        def handle_code_verification(message: Message) -> None:
            print(f"Handling code verification for user {message.from_user.id}")
            with TOTPGenerator(message.from_user.id, message.from_user.first_name) as generator:
                code_is_verified = generator.verify_totp_code(message.text)
                print(f"Code verification result: {code_is_verified}")

            if code_is_verified:
                totp_code_verified(message)
            else:
                totp_code_not_verified(message)

        def totp_code_verified(message: Message) -> None:
            bot_answer = self.jinja.render_templates('a_totp_code_verified.jinja2', context=message.from_user.first_name)
            self.bot.reply_to(message, text=bot_answer)

        def totp_code_not_verified(message: Message) -> None:
            bot_answer = self.jinja.render_templates('a_totp_code_not_verified.jinja2',
                                                     context=message.from_user.first_name)
            self.bot.reply_to(message, text=bot_answer)

        self.bot.enable_save_next_step_handlers(delay=2)

        self.bot.load_next_step_handlers()
