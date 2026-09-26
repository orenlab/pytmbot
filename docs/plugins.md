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
