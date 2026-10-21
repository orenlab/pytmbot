# Security Practices

This document reflects the current security controls implemented in pyTMBot code.

## Access Model

- Access is controlled by `access_control.allowed_user_ids`.
- Privileged operations are restricted by `access_control.allowed_admins_ids`.
- `allowed_admins_ids` must be a subset of `allowed_user_ids` (validated at startup).
- `/getmyid` is intentionally unrestricted for bootstrap setup.

See also: [auth_control.md](auth_control.md).

## Session and 2FA Controls

- Session state is managed by `SessionManager` with expiration and cleanup workers.
- TOTP verification is used for sensitive flows.
- Failed TOTP attempts are tracked and can lead to temporary blocking.
- Authentication/session checks are applied in middleware and critical handlers.

## Docker Runtime Security

- Official container runs as non-root user `pytmbot` (`UID/GID 1001`).
- Docker socket access requires the socket's group (`group_add`); `entrypoint.sh` only reports the socket's group ID
  and the exact fix. See [docker.md](docker.md#docker-socket-access) for least-privilege mode and a filtering socket
  proxy.
- Container actions verify that Docker resolved the exact container that was shown (exact name or a 12+ character ID
  prefix) and are serialized per container.
- Docker views mask environment variable values (except harmless keys such as `PATH` and `TZ`), URL and HTTP header
  credentials, values of secret-looking flags and `KEY=VALUE` pairs, and the password options of common tools
  (`mysql -p`, `curl -u user:password`, `redis-cli -a`, `sshpass -p`, `htpasswd -b`, ...), also inside `sh -c`
  scripts, image history, healthcheck output and container errors. Masking is best effort: it cannot recognize every
  secret.
- Command arguments (container and image Entrypoint, Cmd, Shell and healthcheck test) are shown to admins
  (`allowed_admins_ids`) only; other allowed users see just the executable.
- Recommended runtime hardening:
  - read-only root filesystem
  - `no-new-privileges`
  - dropped Linux capabilities
  - a filtering socket proxy instead of the raw socket (a `:ro` socket mount does not restrict the API)

## Webhook Security

- Webhook server uses:
  - random webhook path segment
  - Telegram secret token verification header
  - Telegram IP allowlist validation
  - request rate limiting + temporary bans
- `webhook_config.trusted_proxy_ips` controls whether forwarded IP headers are trusted.
- Privileged ports are rejected by webhook startup checks.

## Logging and Data Protection

- Log messages are structured and include trace identifiers.
- Sensitive values (tokens, IDs/usernames where applicable) are masked before output.
- Webhook path/token values are masked in lifecycle and error logs.
- At `INFO` and above, exception logs are emitted without full Python traceback dumps.
- Full stack traces are preserved for troubleshooting in `DEBUG`.
- Security-relevant events (auth failures, bans, invalid webhook requests) are explicitly logged.

## Configuration Hardening

- Store secrets only in `pytmbot.yaml`.
- Restrict config permissions (recommended `600`).
- Mount config as read-only in container deployments.
- For read-only containers, set `PYTMBOT_STATE_DIR` to a writable private tmpfs or volume.
- Expose webhook mode only behind a trusted reverse proxy with TLS.

## Operational Baseline

- Use `orenlab/pytmbot:0.5.3` for exact-release reproducibility.
- Use `orenlab/pytmbot:0.5` or `orenlab/pytmbot:stable` for the supported stable line with weekly base-image refreshes.
- Development builds from `feat/*` / `fix/*` publish as `edge-*`; do not treat them as production tags.
- Run periodic vulnerability scans for container image and host.
- Review auth/rate-limit/webhook logs regularly.
