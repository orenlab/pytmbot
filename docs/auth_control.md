# Access Control And 2FA

This document describes the authorization path implemented in code.

Source of truth:

- `pytmbot/middleware/access_control.py`
- `pytmbot/middleware/session_manager.py`
- `pytmbot/middleware/session_wrapper.py`
- `pytmbot/utils/totp.py`

## Request Pipeline

For class middlewares, the runtime order is:

1. `UpdateDedup`
2. `AccessControl`
3. `RateLimit`

The middleware chain is assembled in `pytmbot/pytmbot_instance.py`.

## AccessControl Middleware

`AccessControl` protects all message and callback-query updates.

Current rules:

- Allowed users are read from `access_control.allowed_user_ids`.
- Unauthorized users accumulate attempts.
- After `3` failed attempts, a user is blocked for `3600` seconds.
- Cleanup of expired block state runs in a background thread every `3600` seconds.
- Admin notifications for repeated unauthorized access are suppressed for `300` seconds per user.

Bootstrap exception:

- `/getmyid` is intentionally allowed for unauthorized users.
- This supports initial setup and ID discovery before the allowlist is complete.

## Session Management

`SessionManager` stores per-user authentication state for privileged flows.

States:

- `unauthenticated`
- `processing`
- `authenticated`
- `blocked`

Default timing:

- session timeout: `10` minutes
- cleanup interval: `600` seconds
- user-facing invalid TOTP attempts before a block: `3`
- short-window TOTP burst limit: at least `5` attempts per `60` seconds
- temporary TOTP block duration: `10` minutes

Implementation notes:

- `SessionManager` is a named singleton with weak-reference instance storage.
- Expired sessions are removed by a background cleanup thread.
- Session statistics are exposed to the health subsystem.

## Two-Factor Authentication

2FA is built in. It is not implemented as a plugin.

Current behavior:

- Sensitive handlers use `two_factor_auth_required` from `pytmbot/middleware/session_wrapper.py`.
- TOTP codes are 6-digit codes with a 30-second interval.
- QR codes are generated from the per-user TOTP secret.
- Successful verification transitions the user session to `authenticated`.
- Replayed or invalid codes are rejected by `pytmbot/utils/totp.py`.
- Replay state is persisted in the runtime state directory when it is writable.

## What Is Protected

The bot uses allowlists for all access and applies 2FA only to selected sensitive operations.

Examples of 2FA-protected flows in the current codebase:

- Docker container management actions
- runtime container details
- log access

The exact protected handlers are the ones decorated with `two_factor_auth_required`.

## Observability

Access and authentication subsystems emit structured logs for:

- unauthorized access attempts
- blocks and block expiry
- session lifecycle
- TOTP failures
- privileged action denial

See also:

- [security.md](security.md)
- [settings.md](settings.md)
- [health.md](health.md)
