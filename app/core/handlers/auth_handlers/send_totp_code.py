#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from typing import Union

from telebot.types import Message, CallbackQuery

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session, bot_logger
from app.utilities.totp import TOTPGenerator


class TOTPCodeHandler(HandlerConstructor):
    """
    Handler for sending TOTP code
    """

    def handle_code_verification(self, query: Union[Message, CallbackQuery]):
        if isinstance(query, Message):
            text = query.text
        elif isinstance(query, CallbackQuery):
            text = query.data
        else:
            raise NotImplementedError("Unsupported query type")
        with TOTPGenerator(query.from_user.id, query.from_user.first_name) as generator:
            code_is_verified = generator.verify_totp_code(text)
            print(f"Code verification result: {code_is_verified}")

        if code_is_verified:
            self.totp_code_verified(query)
        else:
            self.totp_code_not_verified(query)

    def totp_code_verified(self, query: Union[Message, CallbackQuery]):
        bot_answer = self.jinja.render_templates('a_totp_code_verified.jinja2',
                                                 context=query.from_user.first_name)
        return self.bot.reply_to(query, text=bot_answer)

    def totp_code_not_verified(self, query: Union[Message, CallbackQuery]):
        bot_answer = self.jinja.render_templates('a_totp_code_not_verified.jinja2',
                                                 context=query.from_user.first_name)
        return self.bot.reply_to(query, text=bot_answer)

    @logged_handler_session
    @bot_logger.catch()
    def handle(self, query: Union[Message, CallbackQuery]):
        """
        Handle the 'Send TOTP code' message by sending the TOTP code to the bot.
        """
        print(f"Handling TOTP code for user {query.from_user.id}")

        if isinstance(query, Message):
            text = query.text
        elif isinstance(query, CallbackQuery):
            text = query.data
        else:
            raise NotImplementedError("Unsupported query type")

        if text is not None:
            self.handle_code_verification(query)
