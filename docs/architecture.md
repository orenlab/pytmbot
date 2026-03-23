# pyTMbot Architecture

This document describes the current runtime architecture.

Source of truth:

- `pytmbot/main.py`
- `pytmbot/pytmbot_instance.py`
- `pytmbot/handlers/`
- `pytmbot/middleware/`
- `pytmbot/adapters/`
- `pytmbot/plugins/`
- `pytmbot/webhook.py`
- `pytmbot/health_system/`

## Runtime Shape

pyTMbot is a synchronous Telegram bot built on `pyTelegramBotAPI`.

Core entrypoints:

- `pytmbot/main.py`: process launcher, signal handling, health startup, runtime supervision
- `pytmbot/pytmbot_instance.py`: bot construction, middleware setup, handler registration, plugin loading, polling /
  webhook start

Runtime modes:

- polling mode
- webhook mode

## Startup Sequence

High-level flow:

1. CLI arguments are parsed.
2. `BotLauncher` validates the environment and builds `PyTMBot`.
3. `PyTMBot` creates the `TeleBot` instance.
4. Middleware chain is registered.
5. Handler chain is registered.
6. Requested plugins are loaded.
7. Health monitoring is initialized.
8. Runtime enters polling or webhook mode.

## Major Subsystems

### Configuration

- `pytmbot/settings.py`
- `pytmbot/models/settings_model.py`
- `pytmbot/globals.py`

Responsibilities:

- load `pytmbot.yaml`
- validate and migrate config
- expose shared runtime settings objects

### Core Runtime

- `pytmbot/main.py`
- `pytmbot/pytmbot_instance.py`

Responsibilities:

- process lifecycle
- startup / shutdown
- polling supervision and restart strategy
- webhook fallback to polling

### Handlers

- `pytmbot/handlers/bot_handlers/`
- `pytmbot/handlers/docker_handlers/`
- `pytmbot/handlers/server_handlers/`
- `pytmbot/handlers/auth_processing/`

Responsibilities:

- Telegram command handling
- callback handling
- Docker UI flows
- server status views
- 2FA interaction flows

### Middleware

- `update_dedup`
- `access_control`
- `rate_limit`
- `session_manager`
- `session_wrapper`

Responsibilities:

- duplicate update rejection
- allowlist enforcement
- request throttling
- authentication state
- 2FA protection for sensitive handlers

### Adapters

- `pytmbot/adapters/docker/`
- `pytmbot/adapters/psutil/`
- `pytmbot/db/influxdb_interface.py`

Responsibilities:

- Docker API access
- host metrics collection
- InfluxDB storage and queries

### Parsers And Templates

- `pytmbot/parsers/`
- `pytmbot/templates/`

Responsibilities:

- Jinja2 template rendering
- render validation
- cache management
- output formatting for Telegram responses

### Plugins

- `pytmbot/plugins/plugin_manager.py`
- `pytmbot/plugins/plugin_interface.py`
- built-in packages in `pytmbot/plugins/monitor/` and `pytmbot/plugins/outline/`

Responsibilities:

- dynamic extension loading
- plugin metadata registration
- plugin UI integration

### Webhook Runtime

- `pytmbot/webhook.py`

Responsibilities:

- FastAPI / Uvicorn server
- webhook registration
- request authentication
- Telegram IP validation
- rate limiting and ban persistence

### Health System

- `pytmbot/health_system/`
- `pytmbot/parsers/health_checker.py`

Responsibilities:

- component-level health checks
- periodic summary generation
- startup and runtime observability

## Request Flow

Polling mode:

1. Telegram update enters `TeleBot`.
2. Class middleware runs.
3. Matching handler executes.
4. Templates / adapters / plugins provide response data.
5. Response is sent through Telegram API.

Webhook mode:

1. FastAPI route validates webhook path and secret token.
2. Client IP is validated against Telegram ranges.
3. Webhook rate limiting is applied.
4. Update payload is validated into `UpdateModel`.
5. `TeleBot.process_new_updates()` handles the update.

## Shared State

The codebase intentionally uses a few shared singletons / cached objects:

- global settings and derived config objects
- `SessionManager`
- `HealthStatus`
- plugin manager
- parser caches

These are part of the runtime design and are referenced by both application code and tests.
