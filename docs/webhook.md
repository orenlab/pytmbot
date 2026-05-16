# Webhook Mode

This document describes the current webhook runtime.

Source of truth:

- `pytmbot/webhook.py`
- `pytmbot/pytmbot_instance.py`
- `pytmbot/main.py`
- `pytmbot/models/telegram_models.py`

## When To Use It

Use webhook mode when you want Telegram to push updates to the bot instead of relying on long polling.

Enable it with:

```bash
uv run python pytmbot/main.py --webhook true --socket_host 0.0.0.0
```

or the Docker image equivalent.

## Required Configuration

The following `webhook_config` fields are required:

- `url`
- `webhook_port`
- `local_port`

Optional fields:

- `trusted_proxy_ips`
- `additional_telegram_ip_ranges`
- `cert`
- `cert_key`

Related CLI fields:

- `--webhook`
- `--socket_host`

## Startup Behavior

At startup the runtime:

1. creates a FastAPI application
2. generates a random webhook path token
3. generates a random Telegram secret token
4. registers the webhook with Telegram
5. starts Uvicorn locally on `local_port`

If webhook startup fails, the launcher falls back to polling mode.

## Security Controls

Webhook requests are accepted only after all of the following checks pass:

- path token matches the active webhook path
- `X-Telegram-Bot-Api-Secret-Token` matches the active secret
- source IP is accepted as Telegram traffic
- request is not blocked by the webhook rate limiter

IP validation details:

- built-in Telegram IPv4 and IPv6 ranges are enforced
- `additional_telegram_ip_ranges` extends the allowlist
- `trusted_proxy_ips` controls whether forwarded headers from reverse proxies are trusted

## Rate Limiting

Two webhook rate limiters are used:

- main webhook path: `10` requests / `10` seconds per IP
- unknown paths / 404s: `5` requests / `10` seconds per IP

Ban behavior:

- repeated abuse can trigger an IP ban
- ban TTL is `3600` seconds
- ban state is persisted under `webhook_ratelimit/<port>/` in the runtime state directory outside pytest when that
  directory is writable

Runtime state directory resolution:

- `PYTMBOT_STATE_DIR` when set
- otherwise `$XDG_STATE_HOME/pytmbot` when `XDG_STATE_HOME` is set
- otherwise `~/.local/state/pytmbot`

## Credential Rotation

Webhook credentials rotate automatically.

Current settings:

- rotation threshold: `10_000` processed requests
- grace period for previous credentials: `300` seconds

During the grace period, old and new credentials are both accepted.

## TLS Behavior

- `local_port` must be `>= 1024`
- if both `cert` and `cert_key` are valid files, Uvicorn can serve HTTPS directly
- if TLS files are missing or invalid, the server logs a warning and continues without in-process TLS
- reverse-proxy TLS termination is supported and is the recommended deployment model

## Reverse Proxy Notes

Recommended pattern:

- public HTTPS listener in Nginx / Traefik / Nginx Proxy Manager
- internal pyTMbot webhook listener on `local_port`
- `trusted_proxy_ips` set only to proxy addresses you control

## Related Docs

- [settings.md](settings.md)
- [docker.md](docker.md)
- [security.md](security.md)
