#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any
import requests
from app import config
from app.core import exceptions


# ------------------------------------------
# Deprecated in next release. Move to psutil
# ------------------------------------------

class GlancesPoller:
    """A class for handling the data from Glances."""

    def __init__(
            self,
            host: str = config.BASE_URI,
            port: int = config.GLANCES_PORT,
            version: int = config.GLANCES_API_VERSION
    ):
        """Initialize the connection."""
        schema = "http"
        self.url = f"{schema}://{host}:{port}/api/{version}"
        self.data: dict[str, Any] = {}
        self.plugins: list[str] = []
        self.values: dict[str, Any] | None = None
        self.requests = requests
        self.response = ''

    def get_data(self, endpoint: str, history: bool = False, history_items: int = 0) -> dict[str, Any]:
        """Retrieve the data."""
        if history:
            url = f"{self.url}/{endpoint}/history/{history_items}"
        else:
            url = f"{self.url}/{endpoint}"

        try:
            self.response = requests.get(url, timeout=10)
        except requests.ConnectionError as err:
            raise exceptions.GlancesApiConnectionError(
                f"Connection to {url} failed"
            ) from err
        except requests.ReadTimeout as err:
            raise exceptions.GlancesApiConnectionError(
                "Request timed out"
            ) from err

        if self.response.status_code == 401:
            raise exceptions.GlancesApiAuthorizationError(
                "Please check your credentials"
            )

        if self.response.status_code != 200 and self.response:
            raise exceptions.GlancesApiNoDataAvailable(
                f"endpoint: '{endpoint}' is not valid"
            )

        return self.response.json()

    @lru_cache
    def check_plugin(self, element: str) -> None:
        plugins = self.get_data("pluginslist", False, 0)
        if element in plugins:
            return
        else:
            raise exceptions.GlancesApiNoDataAvailable("Plugin not found")

    def get_metrics(self, element: str, history: bool = False, history_items: int = 0) -> dict[str, Any]:
        """Get metrics for a monitored element."""
        self.check_plugin(element)
        metrics = self.get_data(element, history, history_items)
        return metrics
