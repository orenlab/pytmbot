# Health System

This document describes the health subsystem implemented in the current code.

Source of truth:

- `pytmbot/health_system/health_system.py`
- `pytmbot/parsers/health_checker.py`
- `pytmbot/main.py`
- `pytmbot/handlers/server_handlers/health_summary.py`

## Overview

The health subsystem provides:

- periodic component-level checks
- a latest-summary singleton for UI and CLI consumers
- startup and runtime health logging
- the `/health` user-facing screen

The launcher builds the health manager after bot initialization and starts monitoring in a background thread.

## Health Levels

Current health levels are:

- `healthy`
- `degraded`
- `unhealthy`
- `critical`
- `offline`

The health summary also exposes:

- `health_ratio`
- `operational`
- `total`
- `duration_ms`
- per-component details

## Registered Checkers

Core checkers:

- `telegram_api` every `90` seconds
- `polling` every `45` seconds
- `sessions` every `60` seconds when a session manager is available
- `system_resources` every `75` seconds when a psutil adapter is available
- `template_parser` every `90` seconds when parser health support is importable

## Health Manager Components

- `HealthMonitor`: stores checker registry, latest snapshot, history, and monitor thread
- `HealthManager`: small wrapper around `HealthMonitor`
- `HealthStatus`: compatibility singleton used by UI and CLI consumers

## Runtime Behavior

The launcher:

1. creates a configured `HealthManager`
2. publishes it into `HealthStatus`
3. starts monitoring with a base interval of `120` seconds
4. logs state changes and periodic status summaries

Health system failures do not abort bot startup. They are logged and the bot continues without health monitoring.

## CLI Health Check

The application CLI exposes:

```bash
uv run python pytmbot/main.py --health_check
```

Exit codes:

- `0`: healthy
- `1`: unhealthy / degraded result exposed as falsey compatibility status
- `2`: no health manager data available

Note:

- `--health_check` reports the current in-process `HealthStatus` compatibility value. It is not a standalone probe that
  bootstraps the full runtime by itself.

## UI Consumption

The server health handler reads `HealthStatus().get_summary()` and renders a Telegram health snapshot from the latest
monitor data.

## Related Docs

- [architecture.md](architecture.md)
- [debug.md](debug.md)
- [security.md](security.md)
