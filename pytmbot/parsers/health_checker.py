#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pytmbot.health_system import HealthResult


class TemplateParserChecker:
    """Simple health checker for template parsing system."""

    def __init__(self, cache_ttl: float = 35.0):
        self._cache_ttl = cache_ttl
        self._last_check = 0.0
        self._cached_result: HealthResult | None = None

    @property
    def name(self) -> str:
        return "template_parser"

    @property
    def interval_seconds(self) -> float:
        return 90.0

    def check_sync(self) -> HealthResult:
        """Check template parser health."""
        current_time = time.time()

        # Use cached result if valid
        if self._cached_result and (current_time - self._last_check) < self._cache_ttl:
            return self._cached_result

        start_time = time.perf_counter()

        try:
            from pytmbot.parsers._parser import _get_cache_stats
            from pytmbot.parsers.validation import get_validation_stats

            cache_stats = _get_cache_stats()
            validation_stats = get_validation_stats()

            latency = (time.perf_counter() - start_time) * 1000

            # Simple health assessment
            template_cache_size = cache_stats.get("template_cache_size", 0)
            validation_errors = validation_stats.get("validation_errors", 0)
            total_validations = validation_stats.get(
                "fast_validations", 0
            ) + validation_stats.get("strict_validations", 0)

            # Determine health level
            from pytmbot.health_system import HealthLevel, HealthResult

            if template_cache_size > 80 or (
                total_validations > 0 and validation_errors / total_validations > 0.2
            ):
                level = HealthLevel.DEGRADED
            elif validation_errors > 0 and total_validations > 0:
                level = (
                    HealthLevel.HEALTHY
                    if validation_errors / total_validations < 0.1
                    else HealthLevel.DEGRADED
                )
            else:
                level = HealthLevel.HEALTHY

            result = HealthResult(
                level=level,
                component=self.name,
                latency_ms=latency,
                details={
                    "cache_size": template_cache_size,
                    "validation_errors": validation_errors,
                    "total_validations": total_validations,
                },
            )

            self._cached_result = result
            self._last_check = current_time
            return result

        except ImportError:
            from pytmbot.health_system import HealthLevel, HealthResult

            return HealthResult(
                level=HealthLevel.OFFLINE,
                component=self.name,
                latency_ms=0.0,
                details={"error": "parser_unavailable"},
            )
        except Exception as e:
            from pytmbot.health_system import HealthLevel, HealthResult

            latency = (time.perf_counter() - start_time) * 1000
            return HealthResult(
                level=HealthLevel.CRITICAL,
                component=self.name,
                latency_ms=latency,
                details={"error": str(e)},
            )


__all__ = ["TemplateParserChecker"]
