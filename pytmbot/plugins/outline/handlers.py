#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>

Outline VPN plugin for pyTMBot

pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import Message

from pytmbot.globals import keyboards
from pytmbot.logs import logged_handler_session
from pytmbot.parsers.compiler import Compiler
from pytmbot.plugins.outline.config import outline_keyboard
from pytmbot.plugins.outline.methods import PluginMethods

plugin_methods = PluginMethods()


# command = ['outline']
@logged_handler_session
def outline_handler(message: Message, bot: TeleBot):
    with Compiler(template_name='outline.jinja2', first_name=message.from_user.first_name) as compiler:
        response = compiler.compile()
    keyboard = keyboards.build_reply_keyboard(plugin_keyboard_data=outline_keyboard)
    return bot.send_message(message.chat.id, response, reply_markup=keyboard)


# regex='Server info'
@logged_handler_session
def handle_server_info(message: Message, bot: TeleBot):
    bot.send_chat_action(message.chat.id, 'typing')
    server_info = plugin_methods.outline_action_manager(action='server_information')

    with Compiler(template_name='server_info.jinja2', first_name=message.from_user.first_name,
                  context=server_info) as compiler:
        response = compiler.compile()

    return bot.send_message(message.chat.id, response)


# regex='Keys'
@logged_handler_session
def handle_keys(message: Message, bot: TeleBot):
    bot.send_chat_action(message.chat.id, 'typing')
    keys = plugin_methods.outline_action_manager(action='key_information')
    with Compiler(template_name='keys.jinja2', first_name=message.from_user.first_name, context=keys) as compiler:
        response = compiler.compile()

    return bot.send_message(message.chat.id, response)


# regex='Traffic'
@logged_handler_session
def handle_traffic(message: Message, bot: TeleBot):
    bot.send_chat_action(message.chat.id, 'typing')
    traffic = plugin_methods.outline_action_manager(action='traffic_information')
    with Compiler(template_name='traffic.jinja2', first_name=message.from_user.first_name, context=traffic) as compiler:
        response = compiler.compile()

    return bot.send_message(message.chat.id, response)
