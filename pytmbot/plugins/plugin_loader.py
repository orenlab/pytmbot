#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from telebot import TeleBot


class PluginLoader:
    def __init__(self, bot):
        self.bot = TeleBot
        self.plugins = {}
        
    def load_plugins(self):
        try:
            from pytmbot.plugins import core
            self.plugins['core'] = core
        except ImportError:
            pass
        