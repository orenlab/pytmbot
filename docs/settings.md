# pyTMbot Configuration Reference

This document describes the runtime configuration accepted by the current code.

Source of truth:

- `pytmbot.yaml.sample`
- `pytmbot/models/settings_model.py`
- `pytmbot/settings.py`

## File Resolution

- The default config path is `pytmbot.yaml`.
- You can override it with `PYTMBOT_CONFIG_PATH`.
- The repository includes `pytmbot.yaml.sample` as the canonical example.

## General Rules

- Many fields are modeled as one-item lists. Follow the sample file exactly.
- `config_version` should normally match the running app version.
- If `config_version` is missing, startup migrates the config to the current version.
- Optional sections may be omitted entirely when the related feature is unused.

## Top-Level Sections

### `config_version`

- Optional, but recommended.
- Current repository sample value: `0.3.0-dev`.
- Legacy configs without this field are auto-migrated.

### `bot_token`

Required.

- `prod_token`: required list with at least one bot token.
- `dev_bot_token`: optional list for development mode.

### `access_control`

Required.

- `allowed_user_ids`: required list of allowed Telegram user IDs.
- `allowed_admins_ids`: required list of admin user IDs.
- `auth_salt`: required list of secret values used for TOTP.

Validation:

- `allowed_admins_ids` must be a subset of `allowed_user_ids`.

### `chat_id`

Required.

- `global_chat_id`: required list with at least one target chat ID for notifications.

### `docker`

Required.

- `host`: required list of Docker daemon endpoints.
- `debug_docker_client`: optional boolean, default `false`.
- `strict_access`: optional boolean, default `false`.

Behavior:

- `strict_access: false` allows degraded runtime when Docker is unavailable.
- `strict_access: true` makes Docker access failures fatal for startup or operations that require Docker.

### `webhook_config`

Optional. Required only when running with `--webhook true`.

- `url`: public host used when registering the Telegram webhook.
- `webhook_port`: public HTTPS port used by Telegram.
- `local_port`: local listening port for the embedded FastAPI / Uvicorn server.
- `cert`: optional certificate path for in-process TLS.
- `cert_key`: optional private key path for in-process TLS.
- `trusted_proxy_ips`: optional list of trusted reverse-proxy IPs or CIDRs.
- `additional_telegram_ip_ranges`: optional list of extra Telegram source ranges.

Validation:

- `trusted_proxy_ips` and `additional_telegram_ip_ranges` must be valid IPs / CIDRs.

Runtime notes:

- `local_port` must be non-privileged (`>= 1024`).
- Missing or invalid TLS files disable in-process TLS and keep the listener in HTTP mode.
- Webhook startup failures fall back to polling mode.

### `plugins_config`

Optional.

#### `plugins_config.monitor`

Used by the built-in `monitor` plugin.

- `tracehold`: required threshold block. The field name is intentionally spelled `tracehold` in the schema and sample.
- `max_notifications`
- `check_interval`
- `reset_notification_count`
- `retry_attempts`
- `retry_interval`
- `monitor_docker`

Notes:

- `reset_notification_count` is a duration in seconds in the shipped sample.
- The monitor plugin also requires the `influxdb` section.

#### `plugins_config.outline`

Used by the built-in `outline` plugin.

- `api_url`
- `cert`

### `influxdb`

Optional. Required when the `monitor` plugin is enabled.

- `url`
- `token`
- `org`
- `bucket`
- `debug_mode`

## Minimal Required Configuration

```yaml
config_version: "0.3.0-dev"

bot_token:
  prod_token:
    - "YOUR_PROD_BOT_TOKEN"

access_control:
  allowed_user_ids:
    - 123456789
  allowed_admins_ids:
    - 123456789
  auth_salt:
    - "YOUR_RANDOM_SALT"

chat_id:
  global_chat_id:
    - 123456789

docker:
  host:
    - "unix:///var/run/docker.sock"
```

## Operational Guidance

- Start from `pytmbot.yaml.sample` instead of writing the file by hand.
- Keep secrets out of version control.
- Mount the final config file read-only in container deployments.
- Revisit [webhook.md](webhook.md), [plugins.md](plugins.md), and [security.md](security.md) for feature-specific
  settings.
