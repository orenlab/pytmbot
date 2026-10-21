#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

# Container health probe: ``python -m pytmbot.health_system.probe``.
#
# Exit codes: 0 healthy, 1 unhealthy, 2 unknown (no snapshot yet). The probe only
# reads the snapshot written by the running bot; it never loads the settings, starts
# the bot or calls the network.

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import NoReturn

from pytmbot.health_system.snapshot import ProbeStatus, evaluate_health_snapshot


def run_probe(path: Path | None = None) -> int:
    """Evaluate the snapshot, print the reason of a failure to stderr, return the code."""
    result = evaluate_health_snapshot(path)
    if result.status is not ProbeStatus.HEALTHY:
        print(f"pytmbot health check: {result.reason}", file=sys.stderr)
    return int(result.status)


def exit_probe(code: int) -> NoReturn:
    """Terminate the probe process with ``code``.

    With inspect mode on (any non-empty ``PYTHONINSPECT``, even ``0``, which images
    up to 0.5.2 set) CPython prints a ``SystemExit`` traceback and exits with 1
    instead of ``code``, so leave through ``os._exit`` after flushing the output.
    """
    if sys.flags.inspect:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)
    sys.exit(code)


def main() -> NoReturn:
    exit_probe(run_probe())


if __name__ == "__main__":
    main()
