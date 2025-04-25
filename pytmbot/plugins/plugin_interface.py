#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from abc import ABC, abstractmethod

from telebot import TeleBot


class PluginInterface(ABC):
    """
    Abstract base class for all pyTMBot plugins.

    This class provides the interface that all plugins must implement to work with the bot.
    It ensures consistent plugin behavior and proper integration with the bot system.

    Attributes:
        bot (TeleBot): The instance of the Telegram bot that the plugin interacts with.

    Example:
        ```python
        class MyPlugin(PluginInterface):
            def register(self) -> None:
                @self.bot.message_handler(commands=['myplugin'])
                def handle_command(message):
                    self.bot.reply_to(message, "Plugin response")
        ```

    Raises:
        TypeError: If the provided bot instance is not a TeleBot object.
    """
    __slots__ = ('bot',)

    def __init__(self, bot: TeleBot) -> None:
        if not isinstance(bot, TeleBot):
            raise TypeError("bot must be an instance of TeleBot")
        self.bot = bot

    @abstractmethod
    def register(self) -> None:
        """
        Register the plugin with the bot system.

        This method must be implemented by all plugin classes. It should set up:
        - Command handlers
        - Message handlers
        - Callback query handlers
        - Any other necessary bot interactions

        Raises:
            NotImplementedError: If the method is not implemented by the plugin class.
            RuntimeError: If registration fails due to bot API issues.
        """
        raise NotImplementedError("Plugin must implement register() method")
