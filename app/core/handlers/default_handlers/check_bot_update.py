#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

import requests
from telebot.types import Message

from app import (
    __github_api_url__,
    __version__,
    bot_logger,
)
from app.core.handlers.handler import Handler
from app.core.logs import logged_handler_session


class BotUpdatesHandler(Handler):
    """Class for handling bot updates"""

    def __init__(self, bot):
        super().__init__(bot)

    @staticmethod
    def __check_bot_update():
        """Check pyTMbot updates"""
        try:
            release_info = {}
            resp = requests.get(
                __github_api_url__,
                timeout=5
            )
            bot_logger.debug("Request has been submitted")
            if resp.status_code == 200:
                release_info.update(
                    {
                        'tag_name': resp.json()['tag_name'],
                        'published_at': (resp.json()['published_at']),
                        'body': resp.json()['body'],
                    },

                )
                bot_logger.debug("Response code - 200")
                return release_info
            else:
                bot_logger.debug(f"Response code - {resp.status_code}. Return empty dict")
                return {}
        except ConnectionError as e:
            bot_logger.error(f"Cant get update info: {e}", exc_info=False)

    @staticmethod
    def _is_bot_development(app_version: str) -> bool:
        """Check bot mode"""
        if len(app_version) > 6:
            is_development = True
        else:
            is_development = False
        return is_development

    def _compile_message(self) -> str:
        """Compile the message to be sent to the bot"""
        none_tpl_name = 'none.jinja2'
        check_system_version = self._is_bot_development(__version__)
        if check_system_version:
            bot_answer = self.jinja.render_templates(
                none_tpl_name,
                thought_balloon=self.get_emoji('thought_balloon'),
                context=(f"You are using the development version: {__version__}. "
                         "We recommend upgrading to a stable release for a better experience.")
            )
            return bot_answer
        else:
            context = self.__check_bot_update()
            if context == {} or not context:
                bot_answer = self.jinja.render_templates(
                    none_tpl_name,
                    thought_balloon=self.get_emoji('thought_balloon'),
                    context="There were some difficulties checking for updates. We should try again later."
                )
                return bot_answer
            else:
                if context.get('tag_name') > __version__:
                    bot_answer = self.jinja.render_templates(
                        'bot_update.jinja2',
                        thought_balloon=self.get_emoji('thought_balloon'),
                        spouting_whale=self.get_emoji('spouting_whale'),
                        calendar=self.get_emoji('calendar'),
                        cooking=self.get_emoji('cooking'),
                        current_version=context.get('tag_name'),
                        release_date=context.get('published_at'),
                        release_notes=context.get('body')
                    )
                    return bot_answer
                elif context.get('tag_name') == __version__:
                    bot_answer = self.jinja.render_templates(
                        none_tpl_name,
                        thought_balloon=self.get_emoji('thought_balloon'),
                        context=f"Current version: {__version__}. No update available."
                    )
                    return bot_answer
                elif context.get('tag_name') < __version__:
                    bot_answer = self.jinja.render_templates(
                        none_tpl_name,
                        thought_balloon=self.get_emoji('thought_balloon'),
                        context=f"Current version: {context.get('tag_name')}. Your version: {__version__}."
                                f" You are living in the future, "
                                f"and I am glad to say that I will continue to grow and evolve!"
                    )
                    return bot_answer

    def handle(self):
        @self.bot.message_handler(commands=['check_bot_updates'])
        @logged_handler_session
        def updates(message: Message) -> None:
            """Check bot update handler"""
            try:
                self.bot.send_chat_action(message.chat.id, 'typing')
                bot_answer = self._compile_message()
                Handler._send_bot_answer(
                    self,
                    message.chat.id,
                    text=bot_answer,
                    parse_mode='HTML'
                )
            except ValueError:
                raise self.exceptions.PyTeleMonBotHandlerError(self.bot_msg_tpl.VALUE_ERR_TEMPLATE)
            except self.TemplateError:
                raise self.exceptions.PyTeleMonBotTemplateError(self.bot_msg_tpl.TPL_ERR_TEMPLATE)
