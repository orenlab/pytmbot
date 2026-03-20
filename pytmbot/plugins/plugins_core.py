#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from pytmbot import globals as g
from pytmbot import logs
from pytmbot.keyboards import keyboards as kb
from pytmbot.middleware.session_manager import SessionManager
from pytmbot.models import handlers_model

logger = logs.Logger()

# Module-level cache for YAML plugin configs: config files don't change at runtime,
# repeated open()+yaml.safe_load() on each plugin command invocation is unnecessary I/O.
_plugin_config_cache: dict[str, dict[str, object]] = {}


class PluginCore:
    __slots__ = (
        "settings",
        "var_config",
        "logger",
        "keyboard",
        "handler_models",
        "session_manager",
    )

    def __init__(self) -> None:
        self.settings = g.settings
        self.var_config = g.var_config
        self.logger = logger
        self.keyboard = kb.Keyboards()
        self.handler_models = handlers_model.HandlerManager
        self.session_manager = SessionManager()
