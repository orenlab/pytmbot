#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from dataclasses import dataclass
from typing import final, Optional

from pydantic import BaseModel


class PluginCoreModel(BaseModel):
    """Core plugin configuration model"""


@dataclass
@final
class PluginsPermissionsModel:
    """Plugin permissions model"""

    base_permission: Optional[bool] = False
    need_running_on_host_machine: Optional[bool] = False
