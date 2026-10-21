# Health System

This document describes the health subsystem implemented in the current code.

Source of truth:

- `pytmbot/health_system/health_system.py`
- `pytmbot/health_system/snapshot.py`
- `pytmbot/health_system/probe.py`
- `pytmbot/parsers/health_checker.py`
- `pytmbot/main.py`
- `pytmbot/handlers/server_handlers/health_summary.py`
- `entrypoint.sh` (`health_check`)

## Overview

The health subsystem provides:

- periodic component-level checks
- a latest-summary singleton for UI consumers
- a health snapshot file for the container health check
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

Required checkers decide whether the bot is healthy:

- `telegram_api` every `90` seconds (`getMe` with a 5 second timeout)
- `polling` every `45` seconds, in polling mode only: reports `unhealthy` once polling was stopped
  (`TeleBot.stop_polling()`), because `infinity_polling()` does not poll again after that

Optional checkers can lower the overall level to `degraded` at most:

- `sessions` every `60` seconds when a session manager is available
- `system_resources` every `75` seconds when a psutil adapter is available
- `template_parser` every `90` seconds when parser health support is importable

In webhook mode (`--webhook true`) Telegram pushes updates to the webhook server, so no `polling` checker is registered.
Plugins do not register checkers.

A component that is not operational is checked again on every monitor cycle instead of waiting for its interval, so a
recovery is noticed quickly.

## Overall Level

The overall level is the worst level of the required components; an optional component counts as `degraded` at worst.
The bot is healthy when the overall level is `healthy` or `degraded`. Consequences:

- a Telegram API outage (timeout, connection error, 5xx) or stopped polling makes the bot unhealthy
- blocked sessions or high process memory show up as `degraded`, never as unhealthy
- if the monitor loop itself fails, a `health_monitor` component is reported as `critical` until the next successful
  cycle

## Health Manager Components

- `HealthMonitor`: stores checker registry, latest snapshot, history, and monitor thread
- `HealthManager`: small wrapper around `HealthMonitor`
- `HealthStatus`: compatibility singleton used by UI consumers
- `HealthSnapshotWriter`: publishes the snapshot read by the container health check

## Runtime Behavior

The launcher:

1. creates a configured `HealthManager` for the run mode (polling or webhook)
2. publishes it into `HealthStatus`
3. starts monitoring with a base interval of `120` seconds (halved while unhealthy, `0.75x` while degraded)
4. writes the health snapshot after every monitor cycle
5. logs state changes and periodic status summaries

Health system failures do not abort bot startup. They are logged and the bot continues without health monitoring; the
container health check then fails because no snapshot is written.

## Health Snapshot

After every monitor cycle, and when the monitor loop fails, the bot writes `health.json` to its state directory:

- `PYTMBOT_STATE_DIR` when set (the official Compose file uses a tmpfs at `/run/pytmbot`)
- otherwise `$XDG_STATE_HOME/pytmbot`
- otherwise `~/.local/state/pytmbot`, or `/dev/shm/pytmbot-<uid>` when that cannot be written (for example a read-only
  root filesystem); the bot and the health check resolve the same path

The file is replaced atomically (temporary file in the same directory, then rename) with mode `0600`; the directory is
created with mode `0700`. It holds the schema version, the bot's PID and process start time, the overall level, the
`healthy` flag, every component level, the write time and a `stale_after` deadline (write time plus twice the base
monitor interval plus `60` seconds, i.e. `300` seconds by default). A clean shutdown removes the file.

The state directory must be writable by the bot user. If it is not, the bot logs `bot.health.snapshot.write.fail` once
(repeated failures are logged at debug level) and keeps running, but the container is reported unhealthy. A directory
set with `PYTMBOT_STATE_DIR` or `XDG_STATE_HOME` is used as is, without the `/dev/shm` fallback.

## Container Health Check

The image `HEALTHCHECK` runs `./entrypoint.sh --health_check`, which runs:

```bash
python -m pytmbot.health_system.probe
```

The probe only reads the snapshot: it does not load the settings, start the bot or call the network. Exit codes:

- `0`: healthy, i.e. the snapshot is fresh, its PID is alive with the recorded start time, and it is marked healthy
- `1`: unhealthy, i.e. the snapshot is stale or dated in the future, the bot process is gone (or its PID now belongs to
  another process), the bot reports an unhealthy level, or the file is unreadable or invalid
- `2`: unknown, i.e. no snapshot yet (the bot is still starting or not running, or the state directory is not
  writable)

For a non-zero result the probe prints one line with the reason to stderr, which Docker keeps in the health log
(`State.Health.Log` in `docker inspect pytmbot`). The entrypoint fails the check for every non-zero code.
Docker's `start_period` (`60` seconds) covers the time until the first snapshot is written.

The same decision is available from the application CLI, which additionally loads the configuration:

```bash
uv run python pytmbot/main.py --health_check
```

Both forms run outside the bot process, so they report on the bot that wrote the snapshot in the configured state
directory. Run one bot instance per state directory.

## UI Consumption

The server health handler reads `HealthStatus().get_summary()` and renders a Telegram health snapshot from the latest
monitor data.

## Related Docs

- [architecture.md](architecture.md)
- [debug.md](debug.md)
- [docker.md](docker.md)
- [security.md](security.md)
