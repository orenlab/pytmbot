#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import ipaddress
from collections import deque
from threading import RLock

from pytmbot.logs import Logger

logger = Logger()


class TelegramIPValidator:
    """Validates if an IP address belongs to Telegram's network ranges."""

    _MAX_VALIDATED_IPS = 4096
    _MAX_REJECTED_IPS = 4096

    def __init__(self, additional_ranges: list[str] | None = None) -> None:
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
        self._validated_ip_order: deque[str] = deque()
        self.rejected_ips: set[str] = set()
        self._rejected_ip_order: deque[str] = deque()
        self._cache_lock = RLock()

        if additional_ranges:
            self._extend_ranges(additional_ranges)

    def _extend_ranges(self, additional_ranges: list[str]) -> None:
        for raw_range in additional_ranges:
            candidate = raw_range.strip()
            if not candidate:
                continue
            try:
                network = ipaddress.ip_network(candidate, strict=False)
            except ValueError:
                logger.warning(
                    "bot.models.telegram_models.additional.range.invalid.warn",
                    ip_range=candidate,
                )
                continue

            if isinstance(network, ipaddress.IPv4Network):
                self.ipv4_ranges.append(network)
            else:
                self.ipv6_ranges.append(network)

    def _remember_validated_ip(self, ip_str: str) -> None:
        """Store validated IP in a bounded in-memory cache."""
        with self._cache_lock:
            if ip_str in self.validated_ips:
                return

            if len(self.validated_ips) >= self._MAX_VALIDATED_IPS:
                oldest_ip = self._validated_ip_order.popleft()
                self.validated_ips.discard(oldest_ip)

            self.validated_ips.add(ip_str)
            self._validated_ip_order.append(ip_str)

    def _remember_rejected_ip(self, ip_str: str) -> None:
        """Store non-Telegram IP in a bounded negative cache."""
        with self._cache_lock:
            if ip_str in self.rejected_ips:
                return

            if len(self.rejected_ips) >= self._MAX_REJECTED_IPS:
                oldest_ip = self._rejected_ip_order.popleft()
                self.rejected_ips.discard(oldest_ip)

            self.rejected_ips.add(ip_str)
            self._rejected_ip_order.append(ip_str)

    def is_telegram_ip(self, ip_str: str) -> bool:
        with self._cache_lock:
            if ip_str in self.validated_ips:
                return True
            if ip_str in self.rejected_ips:
                return False

        try:
            ip = ipaddress.ip_address(ip_str)
            ranges = (
                self.ipv4_ranges
                if isinstance(ip, ipaddress.IPv4Address)
                else self.ipv6_ranges
            )

            for network in ranges:
                if ip in network:
                    self._remember_validated_ip(ip_str)
                    return True
            self._remember_rejected_ip(ip_str)
            return False

        except ValueError:
            logger.error("bot.models.telegram_models.invalid.ip.fail")
            return False
