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

Purpose:

- read-only vulnerability scanning of **existing local Docker images** by immutable image ID
- controlled, offline scans with an externally managed Trivy installation
- admin-only results through existing Rich Messages; no Telegram Widgets required

Requires both `--plugins trivy` **and** `plugins_config.trivy.enabled: true`. The
configuration also requires absolute `executable`, `cache_dir`, and an explicit
`unix:///...` `docker_host`. The plugin is a no-op when disabled.

Security constraints:

- Trivy must be installed and updated separately from pyTMBot. Verify release
  signatures/checksums and pin its version; do not auto-fetch a `latest` binary.
- The **scanner** needs read access to image layers and an offline vulnerability
  database pre-populated under `cache_dir`. Scans use
  `--image-src docker --skip-db-update --skip-java-db-update`. No remote
  registry fallback or automatic image pull is permitted.
- A Docker socket is highly privileged. The filtering socket proxy recommended
  for pyTMBot may **not** implement the image-layer endpoints required by Trivy.
  Do not broaden that proxy's permissions or mount the host's raw Docker socket
  into pyTMBot automatically. Provision and isolate the scanner separately;
  validate the scanner's security boundary before production rollout.
- The scanner CLI is invoked without a shell, with a minimal environment and
  bounded execution/report size. Resource isolation of the scanner **is not**
  provided by the plugin itself; use OS/container controls for CPU, RAM and
  temporary/cache disk limits.
- No scans run until an admin opens `/trivy` in a private chat with a valid
  2FA session. Scan results are sent only to the originating private chat.
- The vulnerability database is not maintained by this plugin. Its freshness
  must be monitored externally; currently results do **not** prove DB freshness.
- The optional plugin does not change Docker resources, fix CVEs, or restart
  containers. Zero findings must not be interpreted as proof of security.

Configuration example (add under `plugins_config:` in `pytmbot.yaml`):

```yaml
  trivy:
    enabled: true
    executable: /opt/trivy/bin/trivy
    docker_host: unix:///run/trivy/docker.sock
    cache_dir: /var/cache/trivy
    timeout_seconds: 180
    max_images: 20
    max_queued_jobs: 2
    max_report_bytes: 2097152
```

This first version exposes an admin-only `/trivy` image picker, `Scan all`,
a bounded single-worker queue, and vulnerability summaries. Persistent history,
scheduler, verified DB provenance and full deployment isolation are not yet
implemented and must not be represented as complete acceptance of #103.

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
