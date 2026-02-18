#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import json
from typing import Any, Literal

from telebot import TeleBot
from telebot.types import Message

from pytmbot.globals import get_emoji_converter, get_keyboards
from pytmbot.parsers.compiler import Compiler
from pytmbot.plugins.outline import config
from pytmbot.plugins.outline.methods import PluginMethods
from pytmbot.plugins.plugin_interface import PluginInterface
from pytmbot.plugins.plugins_core import PluginCore
from pytmbot.utils import set_naturalsize

plugin_methods = PluginMethods()
plugin = PluginCore()
em = get_emoji_converter()
keyboards = get_keyboards()


class OutlinePlugin(PluginInterface):
    def __init__(self, bot: TeleBot):
        """
        Initializes the OutlinePlugin with the given bot instance.

        :param bot: An instance of TeleBot to interact with Telegram API.
        """
        super().__init__(bot)
        self.plugin_logger = plugin.logger

    @staticmethod
    def _get_first_name(message: Message) -> str:
        """Resolve user's first name safely for templates."""
        from_user = message.from_user
        if from_user and from_user.first_name:
            return from_user.first_name
        return "User"

    def outline_handler(self, message: Message) -> None:
        """
        Handles the '/outline' command by sending a compiled response
        using the 'plugin_outline_index.jinja2' template.

        :param message: The incoming Message object from Telegram.
        """
        emojis: dict = {
            "thought_balloon": em.get_emoji("thought_balloon"),
        }

        response = self._compile_template(
            template_name="plugin_outline_index.jinja2",
            first_name=self._get_first_name(message),
            **emojis,
        )
        keyboard = keyboards.build_reply_keyboard(plugin_keyboard_data=config.KEYBOARD)
        self.bot.send_message(
            message.chat.id, response, reply_markup=keyboard, parse_mode="Markdown"
        )

    def handle_server_info(self, message: Message) -> Message | None:
        """
        Handles messages with 'Server info' by sending server information
        compiled using the 'plugin_outline_server_info.jinja2' template.

        :param message: The incoming Message object from Telegram.
        """
        self.bot.send_chat_action(message.chat.id, "typing")

        emojis: dict = {
            "thought_balloon": em.get_emoji("thought_balloon"),
            "label": em.get_emoji("label"),
            "bar_chart": em.get_emoji("bar_chart"),
            "alarm_clock": em.get_emoji("alarm_clock"),
            "key": em.get_emoji("key"),
        }

        server_info = self._get_action_data(action="server_information")
        if server_info is None:
            return self.bot.send_message(
                message.chat.id,
                "Error: Unable to process server information.",
                parse_mode="HTML",
            )

        response = self._compile_template(
            template_name="plugin_outline_server_info.jinja2",
            first_name=self._get_first_name(message),
            context=server_info,
            **emojis,
        )
        return self.bot.send_message(message.chat.id, response, parse_mode="HTML")

    def handle_keys(self, message: Message) -> Message | None:
        """
        Handles messages with 'Keys' by sending key information compiled
        using the 'plugin_outline_keys.jinja2' template.

        :param message: The incoming Message object from Telegram.
        """
        self.bot.send_chat_action(message.chat.id, "typing")

        emojis: dict = {
            "thought_balloon": em.get_emoji("thought_balloon"),
            "minus": em.get_emoji("minus"),
        }

        keys = self._get_action_data(action="key_information")
        if keys is None:
            return self.bot.send_message(
                message.chat.id,
                "Error: Unable to process key information.",
                parse_mode="HTML",
            )

        response = self._compile_template(
            template_name="plugin_outline_keys.jinja2",
            first_name=self._get_first_name(message),
            context=keys,
            **emojis,
        )
        return self.bot.send_message(message.chat.id, response, parse_mode="HTML")

    def handle_traffic(self, message: Message) -> Message | None:
        """
        Handles messages with 'Traffic' by sending traffic information
        compiled using the 'plugin_outline_traffic.jinja2' template.

        :param message: The incoming Message object from Telegram.
        """
        self.bot.send_chat_action(message.chat.id, "typing")

        emojis: dict = {
            "thought_balloon": em.get_emoji("thought_balloon"),
            "minus": em.get_emoji("minus"),
        }

        traffic = self._get_action_data(action="traffic_information")
        if traffic is None:
            return self.bot.send_message(
                message.chat.id,
                "Error: Unable to process traffic data.",
                parse_mode="HTML",
            )

        bytes_transferred = traffic.get("bytesTransferredByUserId", {})
        user_names = self._get_user_names()

        if user_names is None:
            return self.bot.send_message(
                message.chat.id,
                "Error: Unable to process user data.",
                parse_mode="HTML",
            )

        try:
            response = self._compile_template(
                template_name="plugin_outline_traffic.jinja2",
                first_name=self._get_first_name(message),
                context={
                    "bytesTransferredByUserId": bytes_transferred,
                    "userNames": user_names,
                },
                **emojis,
            )
            return self.bot.send_message(message.chat.id, response, parse_mode="HTML")
        except Exception:
            self.plugin_logger.error("bot.plugins.outline.plugin.compiling.sending.fail")
            return self.bot.send_message(
                message.chat.id,
                "Error: An unexpected error occurred.",
                parse_mode="HTML",
            )

    def _get_action_data(
        self,
        action: Literal["key_information", "server_information", "traffic_information"],
    ) -> dict[str, Any] | None:
        """
        Retrieves action data from the plugin methods and processes it.

        :param action: The action to retrieve data for (
        "key_information", "server_information", "traffic_information"
        )
        :return: A dictionary with the action data or None if an error occurs.
        """
        data = plugin_methods.outline_action_manager(action=action)
        if isinstance(data, str):
            try:
                parsed_data = json.loads(data)
                if isinstance(parsed_data, dict):
                    return {str(key): value for key, value in parsed_data.items()}
                return None
            except json.JSONDecodeError:
                self.plugin_logger.error(
                    "bot.plugins.outline.plugin.json.decoding.fail"
                )
        elif isinstance(data, dict):
            return {str(key): value for key, value in data.items()}
        elif hasattr(data, "model_dump"):
            dumped_data = data.model_dump()
            if isinstance(dumped_data, dict):
                return {str(key): value for key, value in dumped_data.items()}
        else:
            self.plugin_logger.error(
                "bot.plugins.outline.plugin.expected.string.fail"
            )
        return None

    def _get_user_names(self) -> dict[str, str] | None:
        """
        Retrieves usernames by their IDs from the key information.

        :return: A dictionary mapping user IDs to their names or None if an error occurs.
        """
        user_info = self._get_action_data(action="key_information")
        if user_info:
            return {key["id"]: key["name"] for key in user_info.get("accessKeys", [])}
        return None

    def _compile_template(
        self,
        template_name: str,
        first_name: str,
        context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Compiles the template with the provided context and first name.

        :param template_name: The name of the Jinja2 template file.
        :param first_name: The first name of the user to personalize the response.
        :param context: Optional context dictionary to pass to the template.
        :param kwargs: Additional keyword arguments to pass to the template.
        :return: The compiled template response as a string.
        """
        with Compiler(
            template_name=template_name,
            first_name=first_name,
            set_naturalsize=set_naturalsize,
            context=context or {},
            **kwargs,
        ) as compiler:
            response = compiler.compile()

        if not isinstance(response, str):
            self.plugin_logger.error(
                "bot.plugins.outline.plugin.compiler.did.fail"
            )
            raise ValueError("Compiler did not return a valid response.")
        return response

    def register(self) -> None:
        """
        Registers message handlers for the plugin's commands and regex patterns.

        :return: The instance of TeleBot with registered handlers.
        """
        wrapped_outline_handler = plugin.logger.session_decorator(self.outline_handler)
        wrapped_server_handler = plugin.logger.session_decorator(self.handle_server_info)
        wrapped_keys_handler = plugin.logger.session_decorator(self.handle_keys)
        wrapped_traffic_handler = plugin.logger.session_decorator(self.handle_traffic)

        self.bot.register_message_handler(wrapped_outline_handler, commands=["outline"])
        self.bot.register_message_handler(wrapped_outline_handler, regexp="Outline VPN")
        self.bot.register_message_handler(
            wrapped_server_handler, regexp="Outline info"
        )
        self.bot.register_message_handler(wrapped_keys_handler, regexp="Keys")
        self.bot.register_message_handler(wrapped_traffic_handler, regexp="Traffic")


__all__ = ["OutlinePlugin"]
