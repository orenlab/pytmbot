#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""


class MessageTpl:
    ERROR_ACCESS_LOG_TEMPLATE = ("Request from: [{0}], user_id [{1}]. Ignored. "
                                 "Reason: user_id not allowed (see BotSettings class in app/settings/bot_settings.py)."
                                 " [lang: {2}, bot: {3}]")
    ERROR_USER_BLOCKED_TEMPLATE = "Sorry, you don't have the rights to access this bot...("
    INFO_USER_SESSION_START_TEMPLATE = "user: [{0}], user_id [{1}]. Handler: [{2}]"
    VALUE_ERR_TEMPLATE = "Invalid message format"
    TPL_ERR_TEMPLATE = "Error parsing template"
