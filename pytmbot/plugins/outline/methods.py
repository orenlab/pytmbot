#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>

Outline VPN plugin for pyTMBot

pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from typing import List, Literal

from pyoutlineapi.client import PyOutlineWrapper
from pyoutlineapi.models import Server, Metrics, AccessKeyList

from pytmbot.logs import bot_logger
from pytmbot.plugins.core import PluginCore
from pytmbot.plugins.outline.config import plugin_config_name
from pytmbot.plugins.outline.models import (
    OutlineConfig,
    OutlineServer,
    BytesTransferredByUserId,
    OutlineKey
)


class PluginMethods(PluginCore):

    def __init__(self):
        super().__init__()
        self.plugin_config = self.load_plugin_config(plugin_config_name, OutlineConfig)
        api_url_secret = self.plugin_config.outline.api_url[0]
        cert_secret = self.plugin_config.outline.cert[0]
        self.api_url = api_url_secret.get_secret_value()
        self.cert = cert_secret.get_secret_value()
        self.client = PyOutlineWrapper(self.api_url, self.cert, verify_tls=False)

    def __fetch_server_information(self) -> Server:
        """
        Fetches server information from the Outline API.

        Returns:
            OutlineServer: An object containing information about the Outline server.
        """
        return self.client.get_server_info()

    def __fetch_traffic_information(self) -> Metrics:
        """
        Fetches traffic information from the Outline API.

        Returns:
            BytesTransferredByUserId: An object containing information about the transferred data by user id.
        """
        return self.client.get_metrics()

    def __fetch_key_information(self) -> AccessKeyList:
        """
        Fetches key information from the Outline API.

        Returns:
            List[OutlineKey]: A list of OutlineKey objects, each containing information about a key.
        """
        return self.client.get_access_keys()

    def outline_action_manager(self,
                               action: str = Literal[
                                   'server_information', 'traffic_information', 'key_information']):
        action_map = {
            "server_information": self.__fetch_server_information,
            "traffic_information": self.__fetch_traffic_information,
            "key_information": self.__fetch_key_information
        }

        try:
            return action_map[action]()
        except KeyError:
            raise ValueError(f"Invalid action: {action}")
        except Exception as error:
            bot_logger.exception(f"Failed at @Outline plugin: {error}")

if __name__ == "__main__":
    print(PluginMethods().outline_action_manager(action="server_information"))
    print(PluginMethods().outline_action_manager(action="traffic_information"))
    print(PluginMethods().outline_action_manager(action="key_information"))
