#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from datetime import date, datetime
from types import TracebackType

type TemplateScalar = str | int | float | bool | None
type TemplateCallableResult = str | int | float | bool | None
type TemplateCallable = Callable[..., TemplateCallableResult]
type TemplateValue = (
    TemplateScalar
    | date
    | datetime
    | TemplateCallable
    | Mapping[str, "TemplateValue"]
    | Sequence["TemplateValue"]
    | AbstractSet["TemplateValue"]
    | Mapping[object, object]
    | Sequence[object]
    | AbstractSet[object]
    | object
)
type TemplateContext = dict[str, TemplateValue]
type TemplateContextInput = Mapping[object, object]
type ParserCacheInfo = dict[str, int | None]
type ParserValidationStats = dict[str, int | str]
type ParserStatsValue = int | bool | ParserCacheInfo | ParserValidationStats
type ParserStats = dict[str, ParserStatsValue]

__all__ = [
    "TracebackType",
    "TemplateScalar",
    "TemplateCallableResult",
    "TemplateCallable",
    "TemplateValue",
    "TemplateContext",
    "TemplateContextInput",
    "ParserCacheInfo",
    "ParserValidationStats",
    "ParserStatsValue",
    "ParserStats",
]
