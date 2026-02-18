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

Recommended secure flow (verify hash before execution):

```bash
curl -fsSLo /tmp/pytmbot-install.sh https://raw.githubusercontent.com/orenlab/pytmbot/refs/heads/master/tools/install.sh
echo "57a5314266327da8be95f819d95cab6ca6d30749e7fdd04854f7331f1802c327  /tmp/pytmbot-install.sh" | sha256sum -c -
sudo bash /tmp/pytmbot-install.sh
```

If your system has no `sha256sum` (for example macOS), use:

```bash
shasum -a 256 /tmp/pytmbot-install.sh
```

Expected SHA256 (`tools/install.sh`, current `master`):

```text
57a5314266327da8be95f819d95cab6ca6d30749e7fdd04854f7331f1802c327
```

Quick one-liner (convenient, but no local pre-execution hash verification):

```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/orenlab/pytmbot/refs/heads/master/tools/install.sh)"
```

Note: with one-liner execution, shell command substitution trims trailing newlines.
Installer shows both:
- `EXECUTED PAYLOAD SHA256`
- `COMPARISON SHA256 (for docs)` (normalized value to compare against published hash)

On startup, installer will stop and require explicit confirmation:

1. Shows installer version, loaded source, official URL, and current SHA256
2. Asks `Type YES if the hash matches documentation`
3. Continues only after exact `YES`

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
3. Creates virtualenv and installs project/runtime dependencies via `pip` (with `pip3` fallback) from `pyproject.toml`
4. Creates systemd unit (`/etc/systemd/system/pytmbot.service`)
5. Enables and starts service

Systemd security includes `ProtectSystem=strict` and related hardening flags.

## Update Flow

Use installer option `3`.

- Local install: updates repo/dependencies via virtualenv `pip` flow and restores existing config
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
