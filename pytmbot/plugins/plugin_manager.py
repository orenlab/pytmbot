#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from typing import Type

from telebot import TeleBot

from pytmbot.logs import bot_logger
from pytmbot.plugins.plugin_interface import PluginInterface


class PluginManager:
    """
    Manages the registration and handling of pyTMBot plugins.

    This class is responsible for registering plugins with the bot. Plugins
    should inherit from `PluginInterface` and implement the `register` method.

    Attributes:
        bot (TeleBot): The instance of the Telegram bot.
        plugins (list): A list to keep track of registered plugin instances.
    """

    def __init__(self, bot: TeleBot):
        self.bot = bot
        self.plugins = []

    # !/venv/bin/python3
    """
    (c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
    pyTMBot - A simple Telegram bot to handle Docker containers and images,
    also providing basic information about the status of local servers.
    """

    class PluginManager:
        """
        Manages the registration and handling of pyTMBot plugins.

        This class is responsible for registering plugins with the bot. Plugins
        should inherit from `PluginInterface` and implement the `register` method.

        Attributes:
            bot (TeleBot): The instance of the Telegram bot.
            plugins (list): A list to keep track of registered plugin instances.
        """

        def __init__(self, bot: TeleBot):
            self.bot = bot
            self.plugins = []

        def register_plugin(self, plugin_class: Type[PluginInterface]):
            """
            Registers a plugin class with the bot.

            This method creates an instance of the plugin class, calls its `register`
            method, and adds it to the list of registered plugins.

            Args:
                plugin_class (Type[PluginInterface]): A class that inherits from `PluginInterface`.

            Raises:
                TypeError: If the provided class does not implement `PluginInterface`.
                AttributeError: If the plugin instance does not implement the `register` method.
            """
            if issubclass(plugin_class, PluginInterface):
                plugin_instance = plugin_class(self.bot)
                if hasattr(plugin_instance, 'register'):
                    plugin_instance.register()
                    self.plugins.append(plugin_instance)
                    bot_logger.info(f'Plugin {plugin_class.__name__} registered successfully.')
                else:
                    bot_logger.error(f'Error: {plugin_class.__name__} does not implement the register method.')
            else:
                bot_logger.error(f'Error: {plugin_class.__name__} does not implement PluginInterface.')
