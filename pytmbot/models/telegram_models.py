#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import ipaddress

from pytmbot.logs import Logger

logger = Logger()


class TelegramIPValidator:
    """Validates if an IP address belongs to Telegram's network ranges."""

    def __init__(self):
        self.ipv4_ranges = [
            ipaddress.ip_network("91.108.56.0/22"),
            ipaddress.ip_network("91.108.4.0/22"),
            ipaddress.ip_network("91.108.8.0/22"),
            ipaddress.ip_network("91.108.16.0/22"),
            ipaddress.ip_network("91.108.12.0/22"),
            ipaddress.ip_network("149.154.160.0/20"),
            ipaddress.ip_network("91.105.192.0/23"),
            ipaddress.ip_network("91.108.20.0/22"),
            ipaddress.ip_network("185.76.151.0/24"),
        ]

        self.ipv6_ranges = [
            ipaddress.ip_network("2001:b28:f23d::/48"),
            ipaddress.ip_network("2001:b28:f23f::/48"),
            ipaddress.ip_network("2001:67c:4e8::/48"),
            ipaddress.ip_network("2001:b28:f23c::/48"),
            ipaddress.ip_network("2a0a:f280::/32"),
        ]

        self.validated_ips: set[str] = set()

    def is_telegram_ip(self, ip_str: str) -> bool:
        if ip_str in self.validated_ips:
            return True

        try:
            ip = ipaddress.ip_address(ip_str)
            ranges = (
                self.ipv4_ranges
                if isinstance(ip, ipaddress.IPv4Address)
                else self.ipv6_ranges
            )

            for network in ranges:
                if ip in network:
                    self.validated_ips.add(ip_str)
                    return True
            return False

        except ValueError:
            logger.error(f"Invalid IP address format: {ip_str}")
            return False
