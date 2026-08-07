# Bot Command Reference

This document describes the user-facing bot interface implemented in the current code.

Source of truth:

- `pytmbot/handlers/handler_manager.py`
- `pytmbot/settings.py`
- `pytmbot/plugins/monitor/config.py`
- `pytmbot/plugins/outline/config.py`

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
| `/check_bot_updates` | allowed users | Checks for newer bot versions                 |
| `/qrcode`            | admins only   | Returns the TOTP QR code used for 2FA setup   |

Provided only when the plugin is loaded:

| Command    | Plugin    | Access        | Behavior                |
|------------|-----------|---------------|-------------------------|
| `/outline` | `outline` | allowed users | Opens Outline VPN views |

## Reply Keyboard Sections

Main menu buttons:

- `Server`
- `Docker`
- `Plugins`
- `Quick view`
- `Health`
- `About me`

Server section buttons:

- `Load average`
- `CPU`
- `Memory load`
- `Sensors`
- `Process`
- `Uptime`
- `File system`
- `Network`

Docker section buttons:

- `Images`
- `Containers`

Authentication buttons:

- `Get QR-code for 2FA app`
- `Enter 2FA code`

Plugin buttons:

- come from loaded plugin index metadata
- `monitor` adds `Monitoring`
- `outline` adds `Outline VPN`

## 2FA Input

TOTP verification accepts a six-digit code:

- `123456`
- `/123456`

Sensitive flows request 2FA only when the action is marked as requiring it.

## Inline Flows

The bot also exposes callback-driven flows that are not slash commands:

- container list pagination and detail screens
- container logs, runtime info, volumes, and networks
- image list pagination and metadata screens
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
- Main menu accents use `KeyboardButton.style`: `primary` for Server / Docker / Quick view / Health, and `danger` for Back to main menu.
- Text-only bot replies re-attach the matching section keyboard automatically.
- Structured screens prefer Telegram Rich Messages (`send_rich_*`) instead of classic `parse_mode` HTML/Markdown where the layout is tabular or sectioned.
- Ephemeral messages removed by auto-delete (for example `/getmyid`, QR setup, exported Docker logs) send a short follow-up that restores the appropriate menu keyboard.

## Related Docs

- [auth_control.md](auth_control.md)
- [plugins.md](plugins.md)
- [architecture.md](architecture.md)
