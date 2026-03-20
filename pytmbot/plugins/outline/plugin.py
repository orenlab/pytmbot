#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import json
from datetime import date, datetime
from typing import Literal

from telebot import TeleBot
from telebot.types import Message

from pytmbot.globals import get_emoji_converter, get_keyboards
from pytmbot.parsers._types import TemplateContext, TemplateValue
from pytmbot.parsers.compiler import Compiler
from pytmbot.plugins.outline import config
from pytmbot.plugins.outline.methods import PluginMethods
from pytmbot.plugins.plugin_interface import PluginInterface
from pytmbot.plugins.plugins_core import PluginCore
from pytmbot.utils import set_naturalsize

plugin = PluginCore()
em = get_emoji_converter()
keyboards = get_keyboards()


# noqa: codeclone[dead-code]
class OutlinePlugin(PluginInterface):
    def __init__(self, bot: TeleBot):
        """
        Initializes the OutlinePlugin with the given bot instance.

        :param bot: An instance of TeleBot to interact with Telegram API.
        """
        super().__init__(bot)
        self.plugin_logger = plugin.logger
        self._plugin_methods: PluginMethods | None = None

    def _get_plugin_methods(self) -> PluginMethods:
        """Lazily initialize Outline methods to avoid import-time side effects."""
        if self._plugin_methods is None:
            self._plugin_methods = PluginMethods()
        return self._plugin_methods

    @staticmethod
    def _get_first_name(message: Message) -> str:
        """Resolve user's first name safely for templates."""
        from_user = message.from_user
        if from_user and from_user.first_name:
            return from_user.first_name
        return "User"

    @staticmethod
    def _pick_value(data: dict[str, object], *keys: str) -> object | None:
        """Pick first non-None value by key variants."""
        for key in keys:
            value = data.get(key)
            if value is not None:
                return value
        return None

    def _normalize_server_context(
        self, server_info: dict[str, object]
    ) -> dict[str, object]:
        """Normalize server payload from different pyoutlineapi response schemas."""
        return {
            "name": self._pick_value(server_info, "name"),
            "metricsEnabled": bool(
                self._pick_value(server_info, "metricsEnabled", "metrics_enabled")
            ),
            "createdTimestampMs": self._pick_value(
                server_info,
                "createdTimestampMs",
                "created_timestamp_ms",
            ),
            "portForNewAccessKeys": self._pick_value(
                server_info,
                "portForNewAccessKeys",
                "port_for_new_access_keys",
            ),
        }

    def _extract_transferred_bytes(
        self, traffic: dict[str, object]
    ) -> dict[str, object]:
        """Normalize transfer metrics key naming across client versions."""
        raw_transferred = self._pick_value(
            traffic,
            "bytesTransferredByUserId",
            "bytes_transferred_by_user_id",
        )
        if not isinstance(raw_transferred, dict):
            return {}
        return {
            str(user_id): bytes_used for user_id, bytes_used in raw_transferred.items()
        }

    def outline_handler(self, message: Message) -> None:
        """
        Handles the '/outline' command by sending a compiled response
        using the 'plugin_outline_index.jinja2' template.

        :param message: The incoming Message object from Telegram.
        """
        response = self._compile_template(
            template_name="plugin_outline_index.jinja2",
            first_name=self._get_first_name(message),
            thought_balloon=em.get_emoji("thought_balloon"),
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

        server_info = self._get_action_data(action="server_information")
        if server_info is None:
            return self.bot.send_message(
                message.chat.id,
                "Error: Unable to process server information.",
                parse_mode="HTML",
            )
        server_context = self._normalize_server_context(server_info)

        response = self._compile_template(
            template_name="plugin_outline_server_info.jinja2",
            first_name=self._get_first_name(message),
            context=server_context,
            thought_balloon=em.get_emoji("thought_balloon"),
            label=em.get_emoji("label"),
            bar_chart=em.get_emoji("bar_chart"),
            alarm_clock=em.get_emoji("alarm_clock"),
            key=em.get_emoji("key"),
        )
        return self.bot.send_message(message.chat.id, response, parse_mode="HTML")

    def handle_keys(self, message: Message) -> Message | None:
        """
        Handles messages with 'Keys' by sending key information compiled
        using the 'plugin_outline_keys.jinja2' template.

        :param message: The incoming Message object from Telegram.
        """
        self.bot.send_chat_action(message.chat.id, "typing")

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
            thought_balloon=em.get_emoji("thought_balloon"),
            minus=em.get_emoji("minus"),
        )
        return self.bot.send_message(message.chat.id, response, parse_mode="HTML")

    def handle_traffic(self, message: Message) -> Message | None:
        """
        Handles messages with 'Traffic' by sending traffic information
        compiled using the 'plugin_outline_traffic.jinja2' template.

        :param message: The incoming Message object from Telegram.
        """
        self.bot.send_chat_action(message.chat.id, "typing")

        traffic = self._get_action_data(action="traffic_information")
        if traffic is None:
            return self.bot.send_message(
                message.chat.id,
                "Error: Unable to process traffic data.",
                parse_mode="HTML",
            )

        bytes_transferred = self._extract_transferred_bytes(traffic)
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
                thought_balloon=em.get_emoji("thought_balloon"),
                minus=em.get_emoji("minus"),
            )
            return self.bot.send_message(message.chat.id, response, parse_mode="HTML")
        except Exception:
            self.plugin_logger.error(
                "bot.plugins.outline.plugin.compiling.sending.fail"
            )
            return self.bot.send_message(
                message.chat.id,
                "Error: An unexpected error occurred.",
                parse_mode="HTML",
            )

    def _get_action_data(
        self,
        action: Literal["key_information", "server_information", "traffic_information"],
    ) -> dict[str, object] | None:
        """
        Retrieves action data from the plugin methods and processes it.

        :param action: The action to retrieve data for (
        "key_information", "server_information", "traffic_information"
        )
        :return: A dictionary with the action data or None if an error occurs.
        """
        data = self._get_plugin_methods().outline_action_manager(action=action)
        if isinstance(data, str):
            try:
                parsed_data = json.loads(data)
                if isinstance(parsed_data, dict):
                    return {str(key): value for key, value in parsed_data.items()}
                if isinstance(parsed_data, list):
                    parsed_items: list[dict[str, object]] = []
                    for item in parsed_data:
                        if isinstance(item, dict):
                            parsed_items.append(
                                {str(key): value for key, value in item.items()}
                            )
                    return {"accessKeys": parsed_items}
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
            if isinstance(dumped_data, list):
                dumped_items: list[dict[str, object]] = []
                for item in dumped_data:
                    if isinstance(item, dict):
                        dumped_items.append(
                            {str(key): value for key, value in item.items()}
                        )
                return {"accessKeys": dumped_items}
        elif isinstance(data, list):
            list_items: list[dict[str, object]] = []
            for item in data:
                if isinstance(item, dict):
                    list_items.append({str(key): value for key, value in item.items()})
                    continue

                model_dump = getattr(item, "model_dump", None)
                if callable(model_dump):
                    dumped_item = model_dump()
                    if isinstance(dumped_item, dict):
                        list_items.append(
                            {str(key): value for key, value in dumped_item.items()}
                        )
            return {"accessKeys": list_items}
        else:
            self.plugin_logger.error("bot.plugins.outline.plugin.expected.string.fail")
        return None

    def _get_user_names(self) -> dict[str, str] | None:
        """
        Retrieves usernames by their IDs from the key information.

        :return: A dictionary mapping user IDs to their names or None if an error occurs.
        """
        user_info = self._get_action_data(action="key_information")
        if user_info:
            users: dict[str, str] = {}
            access_keys_raw = user_info.get("accessKeys")
            if not isinstance(access_keys_raw, list):
                return users

            for key in access_keys_raw:
                if not isinstance(key, dict):
                    continue
                key_id = self._pick_value(key, "id", "key_id")
                key_name = key.get("name")
                if key_id is None or not isinstance(key_name, str):
                    continue
                users[str(key_id)] = key_name
            return users
        return None

    def _compile_template(
        self,
        template_name: str,
        first_name: str,
        context: dict[str, object] | None = None,
        **kwargs: object,
    ) -> str:
        """
        Compiles the template with the provided context and first name.

        :param template_name: The name of the Jinja2 template file.
        :param first_name: The first name of the user to personalize the response.
        :param context: Context dictionary to pass to the template (dict[str, object] | None).
        :param kwargs: Additional keyword arguments to pass to the template.
        :return: The compiled template response as a string.
        """
        normalized_context: TemplateContext = {}
        if context:
            normalized_context = {
                str(key): self._normalize_template_value(value)
                for key, value in context.items()
            }

        template_context: TemplateContext = {
            "first_name": first_name,
            "set_naturalsize": set_naturalsize,
            "context": normalized_context,
        }
        template_context.update(
            {
                str(key): self._normalize_template_value(value)
                for key, value in kwargs.items()
            }
        )

        with Compiler(template_name, True, **template_context) as compiler:
            response = compiler.compile()

        if not isinstance(response, str):
            self.plugin_logger.error("bot.plugins.outline.plugin.compiler.did.fail")
            raise ValueError("Compiler did not return a valid response.")
        return response

    @classmethod
    def _normalize_template_value(cls, value: object) -> TemplateValue:
        """Normalize dynamic plugin payload values to template-safe typed values."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")

        if isinstance(value, (date, datetime)):
            return value

        if isinstance(value, dict):
            return {
                str(dict_key): cls._normalize_template_value(dict_value)
                for dict_key, dict_value in value.items()
            }

        if isinstance(value, list):
            return [cls._normalize_template_value(item) for item in value]

        if isinstance(value, tuple):
            return tuple(cls._normalize_template_value(item) for item in value)

        if isinstance(value, set):
            return {cls._normalize_template_value(item) for item in value}

        if isinstance(value, frozenset):
            return frozenset(cls._normalize_template_value(item) for item in value)

        return str(value)

    def register(self) -> None:
        """
        Registers message handlers for the plugin's commands and regex patterns.

        :return: The instance of TeleBot with registered handlers.
        """
        wrapped_outline_handler = plugin.logger.session_decorator(self.outline_handler)
        wrapped_server_handler = plugin.logger.session_decorator(
            self.handle_server_info
        )
        wrapped_keys_handler = plugin.logger.session_decorator(self.handle_keys)
        wrapped_traffic_handler = plugin.logger.session_decorator(self.handle_traffic)

        self.bot.register_message_handler(wrapped_outline_handler, commands=["outline"])
        self.bot.register_message_handler(wrapped_outline_handler, regexp="Outline VPN")
        self.bot.register_message_handler(wrapped_server_handler, regexp="Outline info")
        self.bot.register_message_handler(wrapped_keys_handler, regexp="Keys")
        self.bot.register_message_handler(wrapped_traffic_handler, regexp="Traffic")


__all__ = ["OutlinePlugin"]
