#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>

Outline VPN plugin for pyTMBot

pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from typing import List, Literal, Union

from pyoutlineapi.client import PyOutlineWrapper
from pyoutlineapi.models import Metrics, Server, AccessKeyList

from pytmbot.logs import bot_logger
from pytmbot.plugins.outline.config import PLUGIN_CONFIG_NAME
from pytmbot.plugins.outline.models import (
    OutlineConfig,
    OutlineServer,
    OutlineKey
)
from pytmbot.plugins.plugins_core import PluginCore


class PluginMethods(PluginCore):

    def __init__(self):
        """
        Initializes the PluginMethods class and sets up the Outline API client.
        """
        super().__init__()
        self.plugin_config = self.load_plugin_config(PLUGIN_CONFIG_NAME, OutlineConfig)
        api_url_secret = self.plugin_config.outline.api_url[0]
        cert_secret = self.plugin_config.outline.cert[0]
        self.api_url = api_url_secret.get_secret_value()
        self.cert = cert_secret.get_secret_value()
        self.client = PyOutlineWrapper(self.api_url, self.cert, verify_tls=False)

    def _fetch_server_information(self) -> Server:
        """
        Fetches server information from the Outline API.

        Returns:
            OutlineServer: An object containing information about the Outline server.
        """
        return self.client.get_server_info()

    def _fetch_traffic_information(self) -> Metrics:
        """
        Fetches traffic information from the Outline API.

        Returns:
            Metrics: An object containing information about the transferred data.
        """
        return self.client.get_metrics()

    def _fetch_key_information(self) -> AccessKeyList:
        """
        Fetches key information from the Outline API.

        Returns:
            List[OutlineKey]: A list of OutlineKey objects, each containing information about a key.
        """
        return self.client.get_access_keys()

    def outline_action_manager(self, action: Literal[
        'server_information', 'traffic_information', 'key_information']) -> Union[
        OutlineServer, Metrics, List[OutlineKey]]:
        """
        Manages actions based on the provided action string and returns the appropriate data.

        Args:
            action (str): The action to perform. Must be one of 'server_information', 'traffic_information', or 'key_information'.

        Returns:
            Union[OutlineServer, Metrics, List[OutlineKey]]: The result of the action.

        Raises:
            ValueError: If an invalid action is provided.
        """
        action_map = {
            "server_information": self._fetch_server_information,
            "traffic_information": self._fetch_traffic_information,
            "key_information": self._fetch_key_information
        }

        if action not in action_map:
            raise ValueError(f"Invalid action: {action}")

        try:
            return action_map[action]()
        except Exception as error:
            bot_logger.exception(f"Failed at @Outline plugin: {error}")
            raise
