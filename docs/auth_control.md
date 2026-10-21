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
4. `CallbackAcknowledger` (answers callback queries that handlers left unanswered)

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
- Expired sessions are removed by a background cleanup thread: authenticated sessions by login time, pending
  (`processing`) sessions after `10` minutes without activity, and blocked sessions only once the block has ended.
- Session statistics are exposed to the health subsystem.

## Two-Factor Authentication

2FA is built in. It is not implemented as a plugin.

Current behavior:

- Sensitive handlers use `two_factor_auth_required` from `pytmbot/middleware/session_wrapper.py`.
- TOTP codes are 6-digit codes with a 30-second interval.
- QR codes are generated from the per-user TOTP secret.
- The secret is derived from the user ID, the Telegram username, and the configured salt. Users without a username
  get a secret derived from the user ID and salt only. Adding or removing a username changes the secret, so the user
  must scan the QR code again (`/qrcode`).
- In group chats, buttons are bound to the user who opened the screen; a press by anyone else is answered with
  "This button belongs to another user." before any 2FA check and never deletes the owner's message.
- 2FA happens only in a private chat with the bot. The QR code (`/qrcode`, "Get 2FA QR code") and code entry
  ("Enter 2FA code", the code itself) are never handled in a group. A protected action in a group posts a short
  notice with an "Open private chat" button (`https://t.me/<bot>?start=2fa`) instead of the 2FA keyboard; the notice
  holds no codes. A code sent to a group during 2FA is deleted when the bot has the right to, is not checked, and does
  not count as an attempt.
- `/start 2fa` in the private chat opens the 2FA screen for an admin, or says that 2FA is already confirmed. The 2FA
  session is per user, so after confirming in private the user repeats the action in the group.
- After a successful code, the "Return" button opens the screen the user was on; for container actions it opens the
  container's Manage screen and never repeats Start/Stop/Restart.
- Successful verification transitions the user session to `authenticated` and resets the failed-attempt counter.
- QR code messages are deleted automatically after 60 seconds. If too many messages are already waiting for
  auto-deletion, the QR code is not sent; if its deletion cannot be scheduled, it is removed right away.
- Replayed or invalid codes are rejected by `pytmbot/utils/totp.py` and count as failed attempts.
- Replay state is persisted in the runtime state directory when it is writable. If writing fails, the error is logged
  and the outdated state file is removed.
- Restart barrier: when the replay state cannot be loaded at startup (for example, the state directory is on tmpfs and
  was wiped), codes that were valid before the process started are rejected. After a restart the user may need to wait
  for the next code (up to about a minute); this rejection does not count as a failed attempt.

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
