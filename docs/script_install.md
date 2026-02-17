# pyTMBot Installation Script (`tools/install.sh`)

`install.sh` is the interactive installer for:

- Docker installation (prebuilt image or source build)
- Local installation (systemd + virtualenv)
- Update flow (auto-detects local vs Docker installation)
- Full uninstall flow

## Requirements

- Root privileges (`sudo` / `root`)
- Supported Linux families:
    - Ubuntu/Debian
    - CentOS/RHEL
    - Fedora
    - Arch Linux
- For local installation: Python `3.13+` (installer can provision Python `3.13`)

## Security Model (Important)

- The script validates that installation directory is safe and absolute (defaults to `/opt/pytmbot`).
- Docker installation is performed from OS package manager by default.
- Docker Compose plugin is installed from OS package manager by default.
- Fallback to Docker convenience script (`https://get.docker.com`) is disabled by default.
- To explicitly allow unverified fallback, set:

```bash
PYTMBOT_ALLOW_UNVERIFIED_DOCKER_SCRIPT=true
```

Use fallback only when package installation is unavailable in your environment.

## Run Installer

```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/orenlab/pytmbot/refs/heads/main/tools/install.sh)"
```

## What Installer Asks For

Minimal required values:

1. Production Telegram bot token
2. Global chat ID
3. Allowed user IDs
4. Allowed admin IDs

Optional values:

1. Development bot token
2. Webhook domain/ports/certificates
3. InfluxDB settings

## Configuration Output

Installer writes config to:

```bash
/opt/pytmbot/pytmbot.yaml
```

Generated config is aligned with current schema:

- includes `config_version`
- uses `null` for optional empty values (`dev_bot_token`, `webhook_config.cert`, `webhook_config.cert_key`)
- writes secure permissions (`600`) for config file

## Installation Modes

### 1) Docker Installation

Two sub-options:

1. Prebuilt image (`orenlab/pytmbot:latest`)
2. Build from source

For prebuilt mode installer generates `/opt/pytmbot/docker-compose.yml` with hardened defaults:

- read-only root filesystem
- dropped capabilities
- `no-new-privileges`
- bind-mounted Docker socket as read-only
- resource limits and log rotation

### 2) Local Installation

Installer performs:

1. Creates service user `pytmbot`
2. Clones repository to `/opt/pytmbot`
3. Creates virtualenv and installs dependencies
4. Creates systemd unit (`/etc/systemd/system/pytmbot.service`)
5. Enables and starts service

Systemd security includes `ProtectSystem=strict` and related hardening flags.

## Update Flow

Use installer option `3`.

- Local install: updates repo/deps and restores existing config
- Docker install:
    - prebuilt image flow: `docker compose pull && docker compose up -d`
    - source flow: `git fetch/reset`, rebuild and start

## Uninstall Flow

Use installer option `4`.

Can remove:

- systemd service
- Docker containers/images/volumes
- installation directory
- `pytmbot` user
- logs

Optional config backup is offered before removal.

## Logs

- Installer log: `/var/log/pytmbot_install.log`
- Local mode app logs: `/var/log/pytmbot.log`, `/var/log/pytmbot_error.log`
- Docker mode runtime logs: `docker logs pytmbot`

## Useful Commands

Local mode:

```bash
sudo systemctl status pytmbot
sudo journalctl -u pytmbot -f
```

Docker mode:

```bash
docker ps --filter "name=pytmbot"
docker logs pytmbot -f
cd /opt/pytmbot && docker compose ps
```

## Notes

- Installer expects Linux host with package manager access.
- If your distro does not provide required Docker packages, use manual Docker installation first, then rerun installer.
