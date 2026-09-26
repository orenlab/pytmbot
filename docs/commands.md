# Bot Command Reference

This document describes the user-facing bot interface implemented in the current code.

Source of truth:

- `pytmbot/handlers/handler_manager.py`
- `pytmbot/settings.py`
- `pytmbot/plugins/monitor/config.py`
- `pytmbot/plugins/outline/config.py`
- `pytmbot/keyboards/keyboards.py`
- `pytmbot/middleware/callback_ack.py`
- `pytmbot/handlers/bot_handlers/fallback.py`

## Slash Commands

Always available in the core bot:

| Command              | Access        | Behavior                                      |
|----------------------|---------------|-----------------------------------------------|
| `/start`             | allowed users | Opens the main menu                           |
| `/help`              | allowed users | Same handler as `/start`                      |
| `/getmyid`           | unrestricted  | Shows user and chat identifiers for bootstrap |
| `/back`              | allowed users | Returns to the main menu                      |
| `/docker`            | allowed users | Opens the Docker section                      |
| `/containers`        | allowed users | Lists containers                              |
| `/images`            | allowed users | Lists images                                  |
| `/server`            | allowed users | Opens the server section                      |
| `/health`            | allowed users | Shows the current health snapshot             |
| `/plugins`           | allowed users | Opens the plugin menu                         |
| `/about`             | allowed users | Shows the version and project links           |
| `/check_bot_updates` | allowed users | Checks for newer bot versions                 |
| `/qrcode`            | admins only   | Returns the TOTP QR code used for 2FA setup   |

Provided only when the plugin is loaded:

| Command    | Plugin    | Access        | Behavior                |
|------------|-----------|---------------|-------------------------|
| `/outline` | `outline` | allowed users | Opens Outline VPN views |

## Reply Keyboard Sections

Main menu buttons:

- `🖥️ Server`
- `🐳 Docker`
- `👀 Quick view`
- `🩺 Health`
- `🧩 Plugins`
- `ℹ️ About`

Server section buttons:

- `📈 Load average`
- `⚡ CPU`
- `🧠 Memory load`
- `🌡️ Sensors`
- `⚙️ Processes`
- `⏱️ Uptime`
- `💾 File system`
- `🌐 Network`

Docker section buttons:

- `📦 Containers`
- `🖼️ Images`

Authentication buttons:

- `📱 Get 2FA QR code`
- `🔢 Enter 2FA code`

Plugin buttons:

- come from loaded plugin index metadata
- `monitor` adds `📊 Monitoring`
- `outline` adds `🪐 Outline VPN`

Button text is matched by its label, so the leading emoji is optional: typing `CPU` or `⚡ CPU` opens the same view, while longer phrases that merely contain a label are ignored.

## 2FA Input

TOTP verification accepts a six-digit code:

- `123456`
- `/123456`

Sensitive flows request 2FA only when the action is marked as requiring it.

## Inline Flows

The bot also exposes callback-driven flows that are not slash commands:

- container list pagination and detail screens
- container logs, runtime info, volumes, and networks
- container actions (start, stop, restart)
- image list pagination, metadata screens, and image update checks
- bot update guide after `/check_bot_updates`
- active sessions from `Uptime`
- quick-view refresh
- health refresh
- detailed network, CPU, memory, and process drill-down views
- plugin-specific inline navigation

## Notes

- There are no separate slash commands for individual server views such as CPU or memory.
- Those views are entered through the reply keyboard or inline navigation after `/server` or `Quick view`.
- Command access is still gated by allowlists, middleware, and optional 2FA.

## Reply Keyboard Behavior

- Section menus (`main`, `server`, `docker`, plugins) use persistent reply keyboards so Telegram clients (notably iOS) keep the menu visible while you browse inline screens.
- Reply keyboard accents use `KeyboardButton.style`: `primary` for Server / Docker / Quick view / Health in the main menu, and `danger` for back-navigation buttons in section and plugin menus. Back-navigation buttons always sit on their own full-width bottom row so the label does not wrap on phones.
- Container action buttons use inline button styles: `danger` for Stop, `primary` for Restart, and `success` for Start.
- Text-only bot replies re-attach the matching section keyboard automatically.
- Structured screens (server metrics, Docker lists and details, menus, update checks, `/getmyid`, plugin screens) are Telegram Rich Messages with native tables; oversized content is trimmed to Telegram limits, and a rejected rich payload falls back to a plain-text message.
- Every inline button press is acknowledged, so the client spinner never hangs; failures show a short "Something went wrong. Please try again." toast.
- Only the latest "Use the menu below to continue." follow-up is kept per chat; older copies are deleted.
- Unrecognized text from an allowed user in a private chat gets a short hint pointing back to the menu instead of silence; a mistyped code during 2FA gets the 2FA hint instead.
- Ephemeral messages removed by auto-delete (for example `/getmyid`, QR setup, exported Docker logs) send a short follow-up that restores the appropriate menu keyboard.

## Related Docs

- [auth_control.md](auth_control.md)
- [plugins.md](plugins.md)
- [architecture.md](architecture.md)
