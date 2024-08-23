#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from outline_vpn.outline_vpn import OutlineVPN

from pytmbot.plugins.core import PluginCore

plugin_core = PluginCore


def build_client():
    try:
        client = OutlineVPN(api_url="https://85.208.109.168:1199/15B4qBw9w_EyPNbY92qcNg",
                            cert_sha256="D0762670AA182692C2CCC8D1C7FCF1692E365D99257DABD6D0F54AA0FC97C633")
        return client
    except Exception as err:
        raise


class OutlinePlugin(PluginCore):
    def __init__(self):
        super().__init__(self)
        self.client = OutlineVPN(api_url="https://85.208.109.168:1199/15B4qBw9w_EyPNbY92qcNg",
                                 cert_sha256="D0762670AA182692C2CCC8D1C7FCF1692E365D99257DABD6D0F54AA0FC97C633")

    def fetch_server_information(self):
        return self.client.get_server_information()

    def fetch_traffic_information(self):
        return self.client.get_transferred_data()

    def fetch_key_information(self):
        return self.client.get_keys()


if __name__ == "__main__":
    print(OutlinePlugin().fetch_key_information())
