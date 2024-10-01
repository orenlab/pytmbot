from telebot import TeleBot
from telebot.types import Message

from pytmbot.globals import keyboards, em
from pytmbot.parsers.compiler import Compiler
from pytmbot.plugins.manager import config
from pytmbot.plugins.plugin_interface import PluginInterface
from pytmbot.plugins.plugins_core import PluginCore

plugin = PluginCore()


class ManagerPlugin(PluginInterface):

    def __init__(self, bot: TeleBot):
        """
        Initializes the MonitoringPlugin with the given bot instance.

        Args:
            bot (TeleBot): An instance of TeleBot to interact with Telegram API.
        """
        super().__init__(bot)
        self.plugin_logger = plugin.bot_logger

    def handle_system_manager(self, message: Message) -> Message:
        keyboard = keyboards.build_reply_keyboard(plugin_keyboard_data=config.KEYBOARD)
        emojis = {
            "thought_balloon": em.get_emoji("thought_balloon"),
            "repeat_single_button": em.get_emoji("repeat_single_button"),
            "counterclockwise_arrows_button": em.get_emoji(
                "counterclockwise_arrows_button"
            ),
            "electric_plug": em.get_emoji("electric_plug"),
            "warning": em.get_emoji("warning"),
            "mobile_phone": em.get_emoji("mobile_phone"),
        }
        with Compiler(
                template_name="plugin_manager_index.jinja2",
                first_name=message.from_user.first_name,
                **emojis
        ) as compiler:
            response = compiler.compile()
        return self.bot.send_message(
            message.chat.id, text=response, reply_markup=keyboard, parse_mode="Markdown"
        )

    def register(self):
        """
        Registers the SystemMonitorPlugin and starts monitoring.

        This method initializes the SystemMonitorPlugin with the loaded configuration
        and the bot instance, then starts monitoring system metrics.
        """
        self.bot.register_message_handler(
            self.handle_system_manager, regexp="Sys Manager", pass_bot=True
        )


__all__ = ["ManagerPlugin"]
