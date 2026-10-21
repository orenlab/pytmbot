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
- `X-Telegram-Bot-Api-Secret-Token` matches the active secret (compared in constant time)
- source IP is accepted as Telegram traffic
- request is not blocked by the webhook rate limiter

IP validation details:

- built-in Telegram IPv4 and IPv6 ranges are enforced
- `additional_telegram_ip_ranges` extends the allowlist; ranges wider than `/16` (IPv4) or `/32` (IPv6) are rejected
  at startup
- `trusted_proxy_ips` controls whether forwarded headers from reverse proxies are trusted; `0.0.0.0/0` and `::/0` are
  rejected at startup
- the client address is resolved as described in [Client Address Resolution](#client-address-resolution)

## Client Address Resolution

The address checked against the Telegram ranges, and used as the rate-limit key, is resolved for each request:

1. Without an `X-Forwarded-For` header, the connecting peer is the client.
2. With the header, the request is refused (`403`) unless `trusted_proxy_ips` is set and the connecting peer is one of
   those proxies.
3. The header is read from the right. Each proxy appends the address it received the request from, so the right
   end is written by your proxies and the left end by whoever sent the request. Entries that are trusted proxies are
   skipped; the first entry that is not a trusted proxy is the client. If every entry is a trusted proxy, the leftmost
   one is the client.
4. Entries left of the client are ignored, even when they are not IP addresses. A malformed entry that has to be read
   (the client or a proxy hop right of it) fails the request with `400`, as does a header longer than 512 characters.
5. IPv4-mapped IPv6 addresses (`::ffff:149.154.167.220`) are treated as their IPv4 address for the proxy check, the
   Telegram check and rate limiting. List IPv4 proxies in plain IPv4 form.

Examples with `trusted_proxy_ips: ['10.0.0.0/8']` and the request arriving from `10.0.0.5`:

| `X-Forwarded-For`                        | Client            |
|------------------------------------------|-------------------|
| `149.154.167.220`                        | `149.154.167.220` |
| `149.154.167.220, 203.0.113.7`           | `203.0.113.7`     |
| `203.0.113.7, 149.154.167.220, 10.0.0.7` | `149.154.167.220` |
| `10.0.0.7, 10.0.0.8`                     | `10.0.0.7`        |

In the second row the left entry was supplied by the sender and is ignored, so the request is refused.

Every proxy hop between Telegram and the bot must be listed in `trusted_proxy_ips`. A hop that is not listed is
taken for the client, and the request is refused because that address is not a Telegram address.

## Rate Limiting

Two webhook rate limiters are used:

- main webhook path: `10` requests / `10` seconds per client address (resolved as above)
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
- `trusted_proxy_ips` set only to proxy addresses you control, one entry (or CIDR) per hop

Nginx on the same host, forwarding to the bot over loopback:

```nginx
location /webhook/ {
    proxy_pass http://127.0.0.1:5001;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

```yaml
webhook_config:
  trusted_proxy_ips:
    - '127.0.0.1/32'
```

`$proxy_add_x_forwarded_for` appends Telegram's address to whatever header the sender supplied. The bot reads the
header from the right, so a forged entry on the left is ignored. `proxy_set_header X-Forwarded-For $remote_addr;`
works as well: it replaces the header with the connecting address.

With several proxies in a row (for example a load balancer in front of nginx), every hop must append to
`X-Forwarded-For` (`$proxy_add_x_forwarded_for` in nginx), and every hop must be in `trusted_proxy_ips`:

```yaml
webhook_config:
  trusted_proxy_ips:
    - '127.0.0.1/32'   # nginx, connecting to the bot
    - '10.0.0.0/24'    # load balancers in front of nginx
```

## Related Docs

- [settings.md](settings.md)
- [docker.md](docker.md)
- [security.md](security.md)
