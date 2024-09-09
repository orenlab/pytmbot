from telebot import TeleBot
from telebot.types import Message

from pytmbot.globals import keyboards
from pytmbot.logs import logged_handler_session
from pytmbot.parsers.compiler import Compiler
from pytmbot.plugins.outline.config import OUTLINE_KEYBOARD
from pytmbot.plugins.outline.methods import PluginMethods
from pytmbot.plugins.plugin_interface import PluginInterface
from pytmbot.plugins.plugins_core import PluginCore

plugin_methods = PluginMethods()

plugin = PluginCore()


class OutlinePlugin(PluginInterface):

    def __init__(self, bot: TeleBot):
        """
        Initializes the OutlinePlugin with the given bot instance.

        :param bot: An instance of TeleBot to interact with Telegram API.
        """
        super().__init__(bot)
        self.plugin_logger = plugin.bot_logger

    @logged_handler_session
    def outline_handler(self, message: Message, bot: TeleBot):
        """
        Handles the '/outline' command by sending a compiled response
        using the 'outline.jinja2' template.

        :param message: The incoming Message object from Telegram.
        :param bot: An instance of TeleBot to interact with Telegram API.
        """
        with Compiler(
            template_name="outline.jinja2", first_name=message.from_user.first_name
        ) as compiler:
            response = compiler.compile()
        keyboard = keyboards.build_reply_keyboard(plugin_keyboard_data=OUTLINE_KEYBOARD)
        return self.bot.send_message(message.chat.id, response, reply_markup=keyboard)

    @logged_handler_session
    def handle_server_info(self, message: Message, bot: TeleBot):
        """
        Handles messages with 'Server info' by sending server information
        compiled using the 'server_info.jinja2' template.

        :param message: The incoming Message object from Telegram.

        """
        self.bot.send_chat_action(message.chat.id, "typing")
        server_info = plugin_methods.outline_action_manager(action="server_information")

        with Compiler(
            template_name="server_info.jinja2",
            first_name=message.from_user.first_name,
            context=server_info,
        ) as compiler:
            response = compiler.compile()

        return self.bot.send_message(message.chat.id, response)

    @logged_handler_session
    def handle_keys(self, message: Message, bot: TeleBot):
        """
        Handles messages with 'Keys' by sending key information compiled
        using the 'keys.jinja2' template.

        :param message: The incoming Message object from Telegram.
        :param bot: An instance of TeleBot to interact with Telegram API.
        """
        self.bot.send_chat_action(message.chat.id, "typing")
        keys = plugin_methods.outline_action_manager(action="key_information")
        with Compiler(
            template_name="keys.jinja2",
            first_name=message.from_user.first_name,
            context=keys,
        ) as compiler:
            response = compiler.compile()

        return self.bot.send_message(message.chat.id, response)

    @logged_handler_session
    def handle_traffic(self, message: Message, bot: TeleBot):
        """
        Handles messages with 'Traffic' by sending traffic information
        compiled using the 'traffic.jinja2' template.

        :param message: The incoming Message object from Telegram.
        :param bot: An instance of TeleBot to interact with Telegram API.
        """
        self.bot.send_chat_action(message.chat.id, "typing")
        traffic = plugin_methods.outline_action_manager(action="traffic_information")
        with Compiler(
            template_name="traffic.jinja2",
            first_name=message.from_user.first_name,
            context=traffic,
        ) as compiler:
            response = compiler.compile()

        return self.bot.send_message(message.chat.id, response)

    def register(self):
        """
        Registers message handlers for the plugin's commands and regex patterns.
        """

        self.bot.register_message_handler(
            self.outline_handler, commands=["outline"], pass_bot=True
        )
        self.bot.register_message_handler(
            self.handle_server_info, regexp="Server info", pass_bot=True
        )
        self.bot.register_message_handler(
            self.handle_keys, regexp="Keys", pass_bot=True
        )
        self.bot.register_message_handler(
            self.handle_traffic, regexp="Traffic", pass_bot=True
        )

        return self.bot


__all__ = ["OutlinePlugin"]
