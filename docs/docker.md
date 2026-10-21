# Docker Runtime

This document describes the Docker image and runtime behavior implemented in the repository.

Source of truth:

- `Dockerfile`
- `entrypoint.sh`
- `.github/workflows/release-to-docker-ci.yml`
- `.github/workflows/rebuild_supported_tags.yml`
- `.github/workflows/development_image_ci.yml`

## Supported Model

Docker and Docker Compose are the only supported deployment models.

Published image:

- `orenlab/pytmbot`

Stable public tags:

- `0.5.3` for an exact release image
- `0.5` for the current supported stable line
- `stable` as the stable-channel alias
- `latest` as an alias of `stable`

Additional tags:

- `0.5-rYYYYMMDD` for dated weekly stable-line rebuilds
- `edge-<branch>` and `edge-sha-<gitsha>` for development images from `feat/*` and `fix/*` branches

See [release_policy.md](release_policy.md) for the full contract.

Supported image architectures:

- `linux/amd64`
- `linux/arm64`

## Runtime Defaults

- base image: Ubuntu (`26.04` in the current `Dockerfile`), without the base image's `pebble` service manager; `tini`
  runs the bot
- container user: `pytmbot`
- user/group id: `1001:1001`
- working directory: `/opt/app`
- default timezone env: `TZ=UTC`
- built-in Docker `HEALTHCHECK` calls `./entrypoint.sh --health_check`, which judges the health snapshot the running bot
  writes to its state directory (see [Health](health.md))
- development images (`edge-*`) track unreleased branch work; production fleets should use the `0.5` stable tags

## Required And Optional Mounts

Required for normal bot startup:

- config file mounted to `/opt/app/pytmbot.yaml`

Required for Docker-management features:

- `/var/run/docker.sock:/var/run/docker.sock:ro`

Optional:

- certificate files referenced by `webhook_config.cert` and `webhook_config.cert_key`

## Docker Socket Access

The bot talks to the Docker Engine API through `/var/run/docker.sock`. Access to that socket is equivalent to root on
the host, so grant it deliberately.

How access is granted:

- the socket is usually `root:docker` with mode `660`, so the bot needs the socket's group ID; find it with
  `stat -c %g /var/run/docker.sock` and pass it with `--group-add <gid>` (Compose: `group_add: ["<gid>"]`)
- for compatibility, the image user is also a member of `root` (gid `0`), gid `1000`, and the image's `docker` group;
  sockets owned by one of these groups (for example rootless Docker or Docker Desktop, where the socket appears as
  `root:root`) work without `group_add`
- `--check-docker` (and every startup) logs the socket's group ID and the exact `--group-add` value when access is
  missing
- mounting the socket with `:ro` does not limit the API: a read-only bind mount still allows connecting to the socket

Least-privilege user: run with `--user 1001:1001 --group-add <gid>` (Compose: `user: "1001:1001"` plus `group_add`).
An explicit `uid:gid` drops the image's compatibility groups, so the process keeps only its own group and the socket
group.

### Restricting the Docker API (recommended)

To limit what a compromised bot could do through Docker, put a filtering socket proxy between the bot and the socket.
The bot uses only these Engine API endpoints:

- `GET`: `/version`, `/_ping`, `/containers/json`, `/containers/{id}/json`, `/containers/{id}/logs`,
  `/containers/{id}/stats`, `/images/json`, `/images/{name}/json`, `/images/{name}/history`
- `POST`: `/containers/{id}/start`, `/containers/{id}/stop`, `/containers/{id}/restart`

Example with [`wollomatic/socket-proxy`](https://github.com/wollomatic/socket-proxy), which allows exactly these
requests and refuses everything else (container create, exec, kill, remove, file copy, image pulls, `/info`):

```yaml
services:
  socket-proxy:
    image: wollomatic/socket-proxy:1
    restart: unless-stopped
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    group_add:
      # Required: the proxy runs unprivileged and needs the socket's group.
      - "${DOCKER_GID:?set DOCKER_GID to the group id of /var/run/docker.sock}"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    command:
      - -listenip=0.0.0.0
      - -allowfrom=pytmbot
      - '-allowGET=/(v1\.[0-9]+/)?(version|_ping|containers/json|containers/[a-zA-Z0-9_.-]+/(json|logs|stats)|images/json|images/.+/(json|history))'
      - '-allowPOST=/(v1\.[0-9]+/)?containers/[a-zA-Z0-9_.-]+/(start|stop|restart)'
    networks: [docker-proxy]

  pytmbot:
    image: orenlab/pytmbot:stable
    container_name: pytmbot
    restart: on-failure
    user: "1001:1001"
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    environment:
      PYTMBOT_STATE_DIR: /run/pytmbot
    tmpfs:
      - /run/pytmbot:noexec,nosuid,nodev,size=10m,uid=1001,gid=1001
    volumes:
      - ./pytmbot.yaml:/opt/app/pytmbot.yaml:ro
    networks: [docker-proxy, default]
    command: --mode prod

networks:
  docker-proxy:
    internal: true
```

Set `DOCKER_GID` once, next to the compose file (the proxy needs the socket's group; Compose refuses to start
without it):

```bash
echo "DOCKER_GID=$(stat -c %g /var/run/docker.sock)" > .env
```

Then point the bot at the proxy in `pytmbot.yaml`:

```yaml
docker:
  host:
    - 'tcp://socket-proxy:2375'
```

Notes:

- `-allowfrom=pytmbot` accepts requests only from the container named `pytmbot`; other containers on the network get
  `403`
- the `docker-proxy` network is internal; the bot also joins `default` to reach Telegram
- the bot logs a `tcp_without_tls` warning for this setup; traffic stays on the internal network
- for a monitoring-only bot, drop the `-allowPOST` line: start/stop/restart are then refused

## Environment Variables

Current runtime-relevant environment variables:

| Variable               | Default                  | Purpose                                                            |
|------------------------|--------------------------|--------------------------------------------------------------------|
| `TZ`                   | `UTC`                    | Container timezone                                                 |
| `STRICT_DOCKER_ACCESS` | `False`                  | Fails startup when Docker access is unavailable if set truthy      |
| `PYTMBOT_CONFIG_PATH`  | unset                    | Overrides the config path when needed                              |
| `PYTMBOT_STATE_DIR`    | `~/.local/state/pytmbot` | Overrides runtime state path (see Runtime State)                   |
| `XDG_STATE_HOME`       | unset                    | Base directory for runtime state when `PYTMBOT_STATE_DIR` is unset |

## Runtime State

Runtime state is used for the container health snapshot, TOTP replay protection and persisted webhook rate-limit bans.

State path resolution:

- `PYTMBOT_STATE_DIR` when set
- otherwise `$XDG_STATE_HOME/pytmbot` when `XDG_STATE_HOME` is set
- otherwise `~/.local/state/pytmbot`
- when that cannot be written (a read-only root filesystem without `PYTMBOT_STATE_DIR`), `/dev/shm/pytmbot-<uid>`, a
  private directory on the tmpfs that Docker mounts in every container; startup logs
  `bot.launcher.state.dir.fallback.info`

A read-only container therefore works without extra settings. To choose the location, set `PYTMBOT_STATE_DIR` to a
writable private tmpfs or volume, for example `/run/pytmbot` as in the official Compose file. A directory set this way
is used as is: if it is not writable, the healthcheck has no data and reports the container unhealthy.

A tmpfs is wiped when the container stops. That is fine: after a restart without saved TOTP replay state, codes issued
before the restart are refused, so wait for the next code (up to a minute).

## Minimal Run

```bash
docker run -d \
  --name pytmbot \
  --restart on-failure \
  -v /path/to/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  --group-add "$(stat -c %g /var/run/docker.sock)" \
  orenlab/pytmbot:stable --mode prod
```

## Minimal Compose

```yaml
services:
  pytmbot:
    image: orenlab/pytmbot:stable
    container_name: pytmbot
    restart: on-failure
    environment:
      TZ: UTC
    group_add:
      - "${DOCKER_GID:-1001}"
    volumes:
      - ./pytmbot.yaml:/opt/app/pytmbot.yaml:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    command: --mode prod
```

To grant access to the Docker socket, set `DOCKER_GID` once, next to the compose file (without it, `group_add`
falls back to the bot's own group `1001` and changes nothing):

```bash
echo "DOCKER_GID=$(stat -c %g /var/run/docker.sock)" > .env
```

## What the Numbers Mean in Docker

Inside a container, the bot reads the container's view of `/proc` and `/sys`. Some kernel counters are not
namespaced and always describe the whole host; others describe only the container. When the bot runs in Docker, the
CPU, Memory, Processes, File system, Disk I/O, Network and Quick view screens end with a one-line note saying whose
numbers they show (for example "Disks: only filesystems mounted into this container."). Outside Docker there are no
notes: everything is the host.

| Screen                                       | Read from                      | Official Compose (`pid: host`)         | Without `pid: host` | With `network_mode: host` |
|----------------------------------------------|--------------------------------|----------------------------------------|---------------------|---------------------------|
| CPU, load average, uptime                    | `/proc/stat`, `/proc/loadavg`  | Host                                   | Host                | Host                      |
| Memory and swap                              | `/proc/meminfo`                | Host                                   | Host                | Host                      |
| Processes, top 10, Monitor alert lists       | `/proc/<pid>`                  | Host                                   | This container only | As set by `pid`           |
| File system                                  | container mount table, statvfs | Filesystems mounted into the container | Same                | Same                      |
| Disk I/O                                     | `/proc/diskstats`              | Host block devices                     | Host                | Host                      |
| Network traffic, interfaces, connections     | `/proc/net`, interface ioctls  | This container                         | This container      | Host                      |
| Sensors                                      | `/sys/class/hwmon`             | Host hardware                          | Host hardware       | Host hardware             |

Notes:

- CPU and memory ignore the container's limits (`cpus`, `mem_limit`): a container capped at 256 MB still shows the
  host's total RAM and the host's CPU usage
- the File system screen lists only the filesystems visible in the container, usually the host filesystem behind
  Docker-managed files such as `/etc/hosts` plus your bind mounts; sizes are those of the backing host filesystem, but
  host partitions that are not mounted into the container are missing and mount points are container paths
- the Monitor plugin uses the same sources: CPU, memory and temperature alerts use host numbers, disk alerts cover only
  filesystems mounted into the container, and CPU/memory alerts add a scope line when their process list may not cover
  the whole host

How the bot tells the scope (no extra privileges needed; the result is logged at startup as `Metric scopes`):

- processes: PID 2 is the kernel thread `kthreadd` only in the host PID namespace; if PID 1 shares the bot's mount
  table, it is the container's own init. Anything else (for example `/proc` mounted with `hidepid`, or Docker nested in
  an LXC container) is reported as "could not tell" instead of guessing
- network: compared with the host's init process, which is visible only with `pid: host`; without it the note reads
  "this container's interfaces, unless network_mode: host"

### Host Disk Numbers

Disk usage is reported for the whole filesystem that contains a mount point, so an empty directory is enough. Create
one on each host filesystem you want to watch and bind-mount it read-only:

```bash
sudo mkdir -p /srv/pytmbot-probe   # keep it empty
```

```yaml
    volumes:
      - /srv/pytmbot-probe:/host/srv:ro
```

The File system screen and the Monitor plugin's disk alerts then include that filesystem (device, size, used, free).
Trade-off: a mounted directory exposes its contents to the bot, so keep probe directories empty. Avoid mounting the host
root (`/:/host:ro`): it makes the whole host file tree readable to the bot, and `:ro` does not prevent reads.

### Host Network and Processes

- `network_mode: host` makes the Network screens show the host's interfaces, traffic and connections. Trade-off: the
  bot shares the host network stack, so it can reach services bound to the host's `127.0.0.1`, any port it opens is
  opened on the host, and Compose `networks:` (including the socket proxy setup above) cannot be combined with it
- `pid: host` (set in the official `docker-compose.yml`) makes Processes show host processes. Trade-off: the bot can
  read the name, owner and command line of every host process, and command lines sometimes carry secrets; with
  `cap_drop: ALL` it cannot signal or trace other users' processes. Without it, Processes and alert process lists
  cover only the bot's container

## Webhook Deployment Notes

- enable with `--webhook true` or bare `--webhook` in the container entrypoint
- set `--socket_host 0.0.0.0` when the webhook listener must bind outside localhost
- `webhook_config.local_port` must be `>= 1024`
- direct public exposure is not the intended model; use a reverse proxy with TLS

## Diagnostics

Generate a TOTP salt:

```bash
docker run --rm orenlab/pytmbot:stable --salt
```

Check Docker socket access:

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  --group-add "$(stat -c %g /var/run/docker.sock)" \
  orenlab/pytmbot:stable --check-docker
```

Read container logs:

```bash
docker logs -f pytmbot
```

## Hardening Guidance

Recommended runtime flags for production:

- `--read-only`
- `--security-opt no-new-privileges`
- `--cap-drop ALL`
- `--user 1001:1001 --group-add <socket gid>` instead of the image's compatibility groups
- a filtering socket proxy instead of the raw socket (see [Restricting the Docker API](#restricting-the-docker-api-recommended))
- writable private tmpfs or volume for `PYTMBOT_STATE_DIR`

Important:

- Docker socket access is privileged host control; a `:ro` socket mount does not make it read-only.
- If Docker access must be mandatory, set `STRICT_DOCKER_ACCESS=True`.

## Related Docs

- [installation.md](installation.md)
- [release_policy.md](release_policy.md)
- [settings.md](settings.md)
- [bot_cli_args.md](bot_cli_args.md)
- [webhook.md](webhook.md)
- [security.md](security.md)
