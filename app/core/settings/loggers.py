#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""


class MessageTpl:
    """Template for logs"""
    ERROR_USER_BLOCKED_TEMPLATE: str = "You do not have permission to access this service. I apologize."
    VALUE_ERR_TEMPLATE: str = "Invalid message format"
    TPL_ERR_TEMPLATE: str = "Error parsing template"
