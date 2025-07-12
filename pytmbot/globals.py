#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import functools
from typing import Final, TYPE_CHECKING

from pytmbot.adapters.psutil.adapter import PsutilAdapter
from pytmbot.keyboards.keyboards import Keyboards, ButtonData
from pytmbot.middleware.session_manager import SessionManager
from pytmbot.settings import (
    settings as app_settings,
    var_config as app_var_config,
    bot_command_settings as app_bot_command_settings,
    bot_description_settings as app_bot_description_settings,
)
from pytmbot.utils import EmojiConverter, is_running_in_docker

if TYPE_CHECKING:
    from pytmbot.settings import (
        settings,
        VarConfig,
        BotCommandSettings,
        BotDescriptionSettings,
    )

# Application metadata - immutable constants
__version__: Final[str] = "0.3.0-dev"
__author__: Final[str] = "Denis Rozhnovskiy <pytelemonbot@mail.ru>"
__license__: Final[str] = "MIT"
__repository__: Final[str] = "https://github.com/orenlab/pytmbot"
__github_api_url__: Final[str] = (
    "https://api.github.com/repos/orenlab/pytmbot/releases/latest"
)

# Settings - direct references to avoid unnecessary copies
settings: settings = app_settings
var_config: VarConfig = app_var_config
bot_commands_settings: BotCommandSettings = app_bot_command_settings
bot_description_settings: BotDescriptionSettings = app_bot_description_settings


# Lazy-loaded singletons to avoid expensive initialization at import time
@functools.lru_cache(maxsize=1)
def get_session_manager() -> SessionManager:
    """Get the global session manager instance."""
    return SessionManager()


@functools.lru_cache(maxsize=1)
def get_keyboards() -> Keyboards:
    """Get the global keyboards instance."""
    return Keyboards()


@functools.lru_cache(maxsize=1)
def get_emoji_converter() -> EmojiConverter:
    """Get the global emoji converter instance."""
    return EmojiConverter()


@functools.lru_cache(maxsize=1)
def get_psutil_adapter() -> PsutilAdapter:
    """Get the global psutil adapter instance."""
    return PsutilAdapter()


@functools.lru_cache(maxsize=1)
def is_docker_environment() -> bool:
    """Check if running in Docker environment."""
    return is_running_in_docker()


# Class reference for typing - no instance creation
ButtonDataType = ButtonData


# Backward compatibility aliases (deprecated - use getter functions)
# These will be removed in a future version
def __getattr__(name: str) -> object:
    """Provide backward compatibility for old global variable access."""
    match name:
        case "session_manager":
            import warnings

            warnings.warn(
                "Direct access to 'session_manager' is deprecated. Use 'get_session_manager()' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            return get_session_manager()
        case "keyboards":
            import warnings

            warnings.warn(
                "Direct access to 'keyboards' is deprecated. Use 'get_keyboards()' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            return get_keyboards()
        case "em":
            import warnings

            warnings.warn(
                "Direct access to 'em' is deprecated. Use 'get_emoji_converter()' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            return get_emoji_converter()
        case "button_data":
            import warnings

            warnings.warn(
                "Direct access to 'button_data' is deprecated. Use 'ButtonDataType' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            return ButtonDataType
        case "psutil_adapter":
            import warnings

            warnings.warn(
                "Direct access to 'psutil_adapter' is deprecated. Use 'get_psutil_adapter()' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            return get_psutil_adapter()
        case "running_in_docker":
            import warnings

            warnings.warn(
                "Direct access to 'running_in_docker' is deprecated. Use 'is_docker_environment()' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            return is_docker_environment()
        case _:
            raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
