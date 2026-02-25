#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from dataclasses import dataclass
from typing import final

from pydantic import BaseModel


class PluginCoreModel(BaseModel):
    """Core plugin configuration model"""


@dataclass(slots=True)
@final
class PluginsPermissionsModel:
    """Plugin permissions model"""

    base_permission: bool | None = False
    need_running_on_host_machine: bool | None = False
