#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from typing import final, Optional

from pydantic import BaseModel
from dataclasses import dataclass


class PluginCoreModel(BaseModel):
    """Core plugin configuration model"""


@dataclass
@final
class PluginsPermissionsModel:
    """Plugin permissions model"""

    base_permission: Optional[bool] = False
    need_running_on_host_machine: Optional[bool] = False
