import json
from typing import Dict, Optional, Literal, Any

from telebot import TeleBot
from telebot.types import Message

from pytmbot.globals import keyboards, em
from pytmbot.parsers.compiler import Compiler
from pytmbot.plugins.outline import config
from pytmbot.plugins.outline.methods import PluginMethods
from pytmbot.plugins.plugin_interface import PluginInterface
from pytmbot.plugins.plugins_core import PluginCore
from pytmbot.utils import set_naturalsize

plugin_methods = PluginMethods()
plugin = PluginCore()


class OutlinePlugin(PluginInterface):
    def __init__(self, bot: TeleBot):
        """
        Initializes the OutlinePlugin with the given bot instance.

        :param bot: An instance of TeleBot to interact with Telegram API.
        """
        super().__init__(bot)
        self.plugin_logger = plugin.logger

    @plugin.logger.session_decorator
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
            first_name=message.from_user.first_name,
            **emojis,
        )
        keyboard = keyboards.build_reply_keyboard(plugin_keyboard_data=config.KEYBOARD)
        self.bot.send_message(
            message.chat.id, response, reply_markup=keyboard, parse_mode="Markdown"
        )

    @plugin.logger.session_decorator
    def handle_server_info(self, message: Message) -> Message:
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
            first_name=message.from_user.first_name,
            context=server_info,
            **emojis,
        )
        self.bot.send_message(message.chat.id, response, parse_mode="HTML")

    @plugin.logger.session_decorator
    def handle_keys(self, message: Message) -> Message:
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
            first_name=message.from_user.first_name,
            context=keys,
            **emojis,
        )
        self.bot.send_message(message.chat.id, response, parse_mode="HTML")

    @plugin.logger.session_decorator
    def handle_traffic(self, message: Message) -> Message:
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
                first_name=message.from_user.first_name,
                context={
                    "bytesTransferredByUserId": bytes_transferred,
                    "userNames": user_names,
                },
                **emojis,
            )
            self.bot.send_message(message.chat.id, response, parse_mode="HTML")
        except Exception as e:
            self.plugin_logger.error(f"Error compiling or sending message: {e}")
            self.bot.send_message(
                message.chat.id,
                "Error: An unexpected error occurred.",
                parse_mode="HTML",
            )

    def _get_action_data(
        self,
        action: Literal["key_information", "server_information", "traffic_information"],
    ) -> Optional[Dict]:
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
                return json.loads(data)
            except json.JSONDecodeError as e:
                self.plugin_logger.error(
                    f"JSON decoding error for action {action}: {e}"
                )
        else:
            self.plugin_logger.error(
                f"Expected string for action {action}, got: {type(data)}"
            )
        return None

    def _get_user_names(self) -> Optional[Dict[str, str]]:
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
        context: Optional[Dict] = None,
        **kwargs: dict[str, Any],
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
                f"Compiler did not return a string: {type(response)}"
            )
            raise ValueError("Compiler did not return a valid response.")
        return response

    def register(self) -> TeleBot:
        """
        Registers message handlers for the plugin's commands and regex patterns.

        :return: The instance of TeleBot with registered handlers.
        """
        self.bot.register_message_handler(self.outline_handler, commands=["outline"])
        self.bot.register_message_handler(self.outline_handler, regexp="Outline VPN")
        self.bot.register_message_handler(
            self.handle_server_info, regexp="Outline info"
        )
        self.bot.register_message_handler(self.handle_keys, regexp="Keys")
        self.bot.register_message_handler(self.handle_traffic, regexp="Traffic")

        return self.bot


__all__ = ["OutlinePlugin"]
