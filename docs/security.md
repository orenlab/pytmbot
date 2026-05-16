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
- Docker socket access is handled via group membership/GID alignment in `entrypoint.sh`.
- Recommended runtime hardening:
  - read-only root filesystem
  - `no-new-privileges`
  - dropped Linux capabilities
  - read-only bind mount for `/var/run/docker.sock`

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

- Use `orenlab/pytmbot:0.3.2` for exact-release reproducibility.
- Use `orenlab/pytmbot:0.3` or `orenlab/pytmbot:stable` for the supported stable line with weekly base-image refreshes.
- Run periodic vulnerability scans for container image and host.
- Review auth/rate-limit/webhook logs regularly.
