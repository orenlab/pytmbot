from __future__ import annotations

from collections.abc import Generator

import pytest

import pytmbot.plugins.plugins_core as plugins_core_module
from pytmbot.plugins.models import PluginCoreModel


class _PluginCfg(PluginCoreModel):
    enabled: bool
    retries: int


@pytest.fixture(autouse=True)
def _clear_plugin_config_cache() -> Generator[None, None, None]:
    plugins_core_module._plugin_config_cache.clear()
    yield
    plugins_core_module._plugin_config_cache.clear()
