# Plugin System

This document describes the plugin system implemented in the current code.

Source of truth:

- `pytmbot/plugins/plugin_manager.py`
- `pytmbot/plugins/plugin_interface.py`
- `pytmbot/plugins/monitor/`
- `pytmbot/plugins/outline/`

## Loading Model

- Plugins are enabled with `--plugins`.
- Startup loads plugins after commands, middleware, and handlers are registered; the hint for unrecognized
  private-chat text is registered after plugins, so plugin handlers take precedence.
- Plugin names are validated before import.
- Discovery is dynamic: the manager imports `pytmbot.plugins.<name>.config` and `pytmbot.plugins.<name>.plugin`.

Example:

```bash
python pytmbot/main.py --plugins monitor outline
```

## Built-In Plugins

### `monitor`

Purpose:

- collects and renders monitoring data
- sends threshold-based notifications
- can watch Docker-related changes

Required configuration:

- `plugins_config.monitor`
- `influxdb`

Key config fields:

- `tracehold`
- `max_notifications`
- `check_interval`
- `reset_notification_count`
- `retry_attempts`
- `retry_interval`
- `monitor_docker`

### `outline`

Purpose:

- integrates with Outline VPN
- exposes Outline information, keys, and traffic views

Required configuration:

- `plugins_config.outline`

Key config fields:

- `api_url`
- `cert`

### `trivy` (experimental; opt-in)

Vulnerability scanning of existing **local** Docker images, using an isolated
Trivy container instead of installing a binary or maintaining a CVE database
inside pyTMBot. The Telegram interface is private-chat, admin- and 2FA-only.

Deployment:

1. `docker-compose.trivy.yml` is a self-contained extension: it includes
   `docker-compose.yml`, so a single `-f` starts the whole stack
   (Docker Compose 2.20+). Do **not** publish the Trivy HTTP ports to the host.
2. Create the two authentication secrets before first start (once):

   ```sh
   mkdir -p secrets
   umask 077
   openssl rand -hex 32 > secrets/trivy_worker_token
   openssl rand -hex 32 > secrets/trivy_server_token
   sudo chgrp 1001 secrets/trivy_worker_token secrets/trivy_server_token
   chmod 0440 secrets/trivy_worker_token secrets/trivy_server_token
   ```

   Secrets are read by the bot (GID 1001) and worker (supplementary GID
   1001). Do not make the files world-readable or commit them.

3. Configure `plugins_config.trivy` in your existing `pytmbot.yaml`:

   ```yaml
   trivy:
     enabled: true
     endpoint: http://trivy-worker:8090
     token_file: /run/secrets/trivy_worker_token
     # Optional private history; mount a persistent volume for this path.
     # history_file: /opt/app/state/trivy-history.sqlite
     max_db_age_hours: 48
     timeout_seconds: 180
     max_images: 20
     max_queued_jobs: 2
     max_report_bytes: 2097152
   ```

   The worker enforces the same hard maxima: `max_db_age_hours` 1–48,
   `timeout_seconds` 10–180 and `max_report_bytes` up to 2 MiB. `max_images`
   bounds the Telegram menu and a "scan all" job; hosts with more images get a
   deterministic sorted subset instead of a failed discovery.

4. Deploy with `docker compose -f docker-compose.trivy.yml up -d --build`.
   Do not add `-f docker-compose.yml` as well: the base file is already
   included, and passing it twice duplicates list-valued settings.
   In Telegram, use `/trivy` or the **Trivy scans** button in `/plugins`.
   Optional persistent history may be enabled with `history_file`, but requires
   a separate persistent private directory.

   The extension replaces the `pytmbot` service `command`. If your base Compose
   file already loads other plugins, list them all explicitly, for example
   `command: ["--log-level", "INFO", "--plugins", "monitor,trivy"]`.

The Trivy Compose file adds a digest-pinned official Trivy 0.76.2 server,
a small HTTP worker derived from the official Trivy image, and a Docker
socket proxy restricted to image reads and with POST disabled. Trivy server
automatically downloads and updates the vulnerability database to its own
persistent Docker volume. No manual Trivy binary or CVE DB setup is necessary.

Security notes:

- The worker accepts only immutable `sha256:<64 hex>` local image IDs over an
  authenticated private HTTP endpoint. It does not accept arbitrary commands,
  remote image references, paths, or scanner flags.
- The bot keeps its existing Docker permissions. The scanner proxy
  *separately* mounts the host Docker socket and permits only the configured
  GET image API surface. A `:ro` socket mount alone is **not** a
  read-only Docker API security boundary.
- Images can contain secrets, hostile files and sensitive application data.
  Restrict access to the worker's network and host; review residual risks
  before installing this overlay on a production host.
- CPU, memory, process count, temporary disk, scan duration, worker queue and
  report sizes are bounded. The worker scans at most 1 GiB per image and fails
  closed when the Trivy report exceeds 2 MiB. The Trivy server needs outbound
  access to maintain its database; its `/tmp` extraction space is configurable
  with `TRIVY_DB_TMPFS_SIZE` (default `768m`). The worker and the Docker proxy
  are not published publicly.
- The worker writes one JSON log record per line to stderr (same `ts`/`level`/
  `msg` shape as pyTMBot) and never logs tokens, request paths or full image
  IDs. Set `TRIVY_WORKER_LOG_LEVEL` (default `INFO`) to change verbosity.
  pyTMBot itself logs through the shared `pytmbot.logs.Logger` singleton.
- `/healthz` in the worker is unauthenticated by design and only reports
  liveness. Keep the `trivy_control` network private; never publish port 8090.
- Trivy results indicate **known** vulnerabilities, not proof of exploitation
  or complete security. Failures and stale CVE databases must not be reported
  as clean scans.
- `0.5.5` is still a release candidate. Run the real end-to-end
  `Trivy Docker Integration` workflow before the production gate can pass.

## Plugin Package Contract

A plugin package lives under `pytmbot/plugins/<plugin_name>/`.

Expected files:

- `config.py`
- `plugin.py`

`config.py` must provide:

- `PLUGIN_NAME`
- `PLUGIN_VERSION`
- `PLUGIN_DESCRIPTION`
- `PLUGIN_PERMISSIONS`

Optional metadata:

- `PLUGIN_COMMANDS`
- `PLUGIN_INDEX_KEY`
- `PLUGIN_RESOURCE_LIMITS`

`plugin.py` must expose at least one class that:

- subclasses `PluginInterface`
- accepts `TeleBot` in the constructor
- implements `register()`

## Validation And Security Rules

Plugin names must satisfy the current manager rules:

- lowercase letters and underscores only
- no path traversal
- no slashes or shell control characters
- no hidden paths
- no direct `.py` file loading

The manager also rejects plugins with invalid permissions metadata or missing required config constants.

## Runtime Notes

- Plugin instances are tracked by the manager and cleaned up on exit.
- Plugin metadata is merged into the plugin menu shown by the bot.
- Plugins are startup-time extensions; there is no hot-reload mechanism in the current runtime.
- Structured plugin screens should use the rich message helpers (`send_rich_bot_message` and friends in
  `pytmbot/handlers/handlers_util/rich_messages.py`) and follow the rich template layout described in
  [development.md](development.md#rich-message-templates).
- Register reply-button handlers with `reply_button_pattern(label)` from `pytmbot/keyboards/keyboards.py` so labels
  match exactly, with or without the emoji.

## Related Docs

- [settings.md](settings.md)
- [architecture.md](architecture.md)
- [development.md](development.md)
