#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.

User-facing texts shared by Docker inline handlers.

Callback alerts are limited to 200 characters by Telegram.
"""

from __future__ import annotations

from typing import Final

DOCKER_UNAVAILABLE_TEXT: Final[str] = (
    "Docker is unavailable right now. Check that the Docker daemon is running "
    "and try again."
)
CONTAINER_NOT_FOUND_TEXT: Final[str] = (
    "Container not found. It may have been removed or recreated — "
    "open it again from the containers list."
)
INVALID_CONTAINER_REF_TEXT: Final[str] = "This container reference is invalid."
CONTAINER_DETAILS_FAILED_TEXT: Final[str] = "Couldn't load container details right now."
DOCKER_REQUEST_FAILED_TEXT: Final[str] = (
    "Docker reported an error for this container. Try again or check the bot logs."
)
