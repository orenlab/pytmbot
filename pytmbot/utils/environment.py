#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import os
import sys
from functools import lru_cache, cache
from typing import Any


@lru_cache(maxsize=None)
def is_running_in_docker() -> bool:
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/self/cgroup", "r") as f:
            for line in f:
                if "docker" in line:
                    return True
    except FileNotFoundError:
        pass
    if "DOCKER_CONTAINER" in os.environ:
        return True
    return False


@cache
def get_environment_state() -> dict[str, Any]:
    return {
        "Python path": sys.executable,
        "Python version": sys.version,
        "Module path": sys.path,
        "Command args": sys.argv,
        "Running on": "Docker" if is_running_in_docker() else "Bare Metal",
    }
