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

    Plugins should inherit from this class and implement the `register` method,
    which will be used to register the plugin with the bot.

    Attributes:
        bot (TeleBot): The instance of the Telegram bot that the plugin interacts with.
    """

    def __init__(self, bot: TeleBot):
        self.bot = bot

    @abstractmethod
    def register(self):
        """
        Method that must be implemented in each plugin.

        This method should contain the logic for registering the plugin, such as
        setting up command handlers, adding to menus, and other actions necessary
        for the plugin to function.

        Raises:
            NotImplementedError: If the method is not implemented in a subclass.
        """
        pass
