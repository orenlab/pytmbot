#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>

Outline VPN plugin for pyTMBot

pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from typing import List, Literal

from outline_vpn.outline_vpn import OutlineVPN

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
        self.client = OutlineVPN(self.api_url, self.cert)

    def __fetch_server_information(self) -> OutlineServer:
        """
        Fetches server information from the Outline API.

        Returns:
            OutlineServer: An object containing information about the Outline server.
        """
        return OutlineServer(**self.client.get_server_information())

    def __fetch_traffic_information(self) -> BytesTransferredByUserId:
        """
        Fetches traffic information from the Outline API.

        Returns:
            BytesTransferredByUserId: An object containing information about the transferred data by user id.
        """
        return BytesTransferredByUserId(**self.client.get_transferred_data())

    def __fetch_key_information(self) -> List[OutlineKey]:
        """
        Fetches key information from the Outline API.

        Returns:
            List[OutlineKey]: A list of OutlineKey objects, each containing information about a key.
        """
        keys: List[OutlineKey] = self.client.get_keys()
        return keys

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
