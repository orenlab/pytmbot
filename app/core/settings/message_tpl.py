#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""


class MessageTpl:
    ACCESS_SUCCESS = "Request from: [{0}], user_id [{1}]. Accepted."
    ERROR_ACCESS_LOG_TEMPLATE = ("Request from: [{0}] user_id [{1}]. Ignored. "
                                 "Reason: user_id not allowed (see BotSettings class in app/settings/bot_settings.py)")
    ERROR_USER_BLOCKED_TEMPLATE = "Sorry, you don't have the rights to access this bot...("
    INFO_USER_SESSION_START_TEMPLATE = "user: [{0}] user_id: [{1}] handler: [{2}]"
    VALUE_ERR_TEMPLATE = "Invalid message format"
    TPL_ERR_TEMPLATE = "Error parsing template"
    HANDLER_START_TEMPLATE = "Start handling session. User: {0}, user_id: {1}, lang: {2}, is_bot: {3})"
