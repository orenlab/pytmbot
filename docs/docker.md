# pyTMbot Docker Image

[![Docker Pulls](https://img.shields.io/docker/pulls/orenlab/pytmbot)](https://hub.docker.com/r/orenlab/pytmbot)
[![Image Size](https://img.shields.io/docker/image-size/orenlab/pytmbot/latest)](https://hub.docker.com/r/orenlab/pytmbot)
[![GitHub Release](https://img.shields.io/github/v/release/orenlab/pytmbot)](https://github.com/orenlab/pytmbot/releases)

A secure, lightweight Docker container for pyTMbot - your Telegram-based monitoring and management solution.

pyTMbot is Docker-only: Docker / Docker Compose is the only supported installation and runtime model.

## Quick Reference

- **Maintained by**: [OrenLab Team](https://github.com/orenlab)
- **Where to file issues**: [GitHub Issues](https://github.com/orenlab/pytmbot/issues)
- **Supported architectures**: `amd64`, `arm64`
- **Base image**: Ubuntu
- **Published image artifact details**:
    - **Image**: `orenlab/pytmbot`
    - **Supported tags**:
        - `latest` - Latest stable release
        - `X.Y.Z` - Specific version releases (e.g., `1.2.3`)
        - `ubuntu-dev` - Development version

## Security Features

- Runs as non-root user (`pytmbot`) by default
- Read-only container filesystem
- Minimal base image footprint (Ubuntu LTS runtime)
- Regular security updates
- Dropped unnecessary capabilities
- No privilege escalation allowed
- Isolated network with disabled inter-container communication
- Temporary filesystem mounts for security

## Prerequisites

- Docker Engine 20.10+
- Docker Compose v2.0+ (recommended)
- Internet connection for initial pull
- For Docker-management features: mount `/var/run/docker.sock` as read-only

## Quick Start

```bash
# 1. Generate authentication salt
docker run --rm orenlab/pytmbot:latest --salt

# 2. Create config directory
mkdir -p /etc/pytmbot

# 3. Download sample config
curl -o /etc/pytmbot/config.yaml \
  https://raw.githubusercontent.com/orenlab/pytmbot/master/pytmbot.yaml.sample

# 4. Edit configuration
nano /etc/pytmbot/config.yaml

# 5. Run container
docker run -d \
  --name pytmbot \
  --restart on-failure \
  --env TZ="UTC" \
  --volume /etc/pytmbot/config.yaml:/opt/app/pytmbot.yaml:ro \
  --volume /var/run/docker.sock:/var/run/docker.sock:ro \
  --security-opt no-new-privileges \
  --read-only \
  --cap-drop ALL \
  --pid host \
  --memory 256m \
  --cpu-shares 512 \
  orenlab/pytmbot:latest --log-level INFO
```

## Docker Compose Usage (Recommended)

```yaml
services:
  pytmbot:
    image: orenlab/pytmbot:latest
    container_name: pytmbot
    restart: on-failure
    environment:
      - TZ=UTC
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /etc/pytmbot/config.yaml:/opt/app/pytmbot.yaml:ro
    security_opt:
      - no-new-privileges
    read_only: true
    cap_drop:
      - ALL
    pid: host
    mem_limit: 256m
    memswap_limit: 256m
    cpu_shares: 512
    ulimits:
      nproc: 65535
      nofile:
        soft: 20000
        hard: 40000
    networks:
      - pytmbot_network
    tmpfs:
      - /tmp:noexec,nosuid,nodev,size=100m
      - /var/tmp:noexec,nosuid,nodev,size=50m
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    command: --log-level INFO

networks:
  pytmbot_network:
    driver: bridge
    # If the bot starts without plug-ins, then we disable network interaction:
    driver_opts:
      com.docker.network.bridge.enable_icc: "false"
    # The case when the bot is running with the Monitor plugin enabled:
    #driver_opts:
    #  com.docker.network.bridge.enable_icc: "true"
    ipam:
      driver: default
      config:
        - subnet: 172.20.0.0/16
```

## Configuration

### General Bot Settings (Required)

- **Bot Token**: Provide `prod_token` or `dev_bot_token` depending on mode
- **Chat ID**: Set `global_chat_id` for notifications
- **Access Control**: Configure `allowed_user_ids`, `allowed_admins_ids`, and `auth_salt`

### Webhook Configuration (if using `--webhook`)

- **webhook_config**: Complete all parameters in the webhook configuration section
- **trusted_proxy_ips**: Configure trusted reverse-proxy IPs/CIDRs when forwarded headers are used
- **Security Note**: Webhook server cannot run on privileged ports (`<1024`, including `80` and `443`). Use a reverse
  proxy (Nginx, Nginx Proxy Manager, Traefik, etc.).

## Command Line Arguments

For full core CLI reference, see
[`docs/bot_cli_args.md`](https://github.com/orenlab/pytmbot/blob/master/docs/bot_cli_args.md).

Docker image entrypoint supports:

| Argument          | Type   | Default     | Description                                                          |
|-------------------|--------|-------------|----------------------------------------------------------------------|
| `--mode`          | `str`  | `prod`      | Bot mode: `dev` / `prod`.                                            |
| `--log-level`     | `str`  | `INFO`      | Log level: `TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `--log-format`    | `str`  | mode-based  | Log format: `human` / `json`.                                        |
| `--colorize_logs` | `bool` | `True`      | Enable/disable colorized logs (`true`/`false`).                      |
| `--plugins`       | `list` | `[]`        | Plugin list (for example: `--plugins monitor outline`).              |
| `--webhook`       | `bool` | `False`     | Enable webhook mode (`--webhook` or `--webhook true/false`).         |
| `--socket_host`   | `str`  | `127.0.0.1` | Socket host for webhook mode.                                        |
| `--debug`         | `flag` | `False`     | Shortcut for `--mode dev --log-level DEBUG`.                         |
| `--health_check`  | `flag` | `False`     | Run entrypoint health check and exit.                                |
| `--check-docker`  | `flag` | `False`     | Entrypoint utility: check Docker socket access and exit.             |
| `--salt`          | `flag` | `False`     | Entrypoint utility: generate auth salt and exit.                     |

## Plugin System

pyTMbot supports various plugins to extend functionality:

### Available Plugins

- **Monitor**: System and Docker container monitoring (requires InfluxDB).
  Configure `url`, `token`, `org`, `bucket`, and monitoring thresholds in the `monitor` config section.
- **Outline**: Outline VPN management and monitoring.
  Configure `api_url` and `cert` paths in the `outline` config section.

### Plugin Usage

Enable specific plugins:

```bash
docker run ... orenlab/pytmbot:latest --plugins monitor
```

Enable multiple plugins:

```bash
docker run ... orenlab/pytmbot:latest --plugins monitor outline
```

Development mode with debug logging:

```bash
docker run ... orenlab/pytmbot:latest --mode dev --log-level DEBUG --plugins monitor
```

## Production Deployment

### Security Best Practices

- Use `--mode prod` for production deployments
- Set appropriate log levels (`INFO` or `ERROR` for production)
- Configure webhook mode behind reverse proxy
- Use read-only filesystem and dropped capabilities
- Implement proper network isolation
- Enable `STRICT_DOCKER_ACCESS=True` in production if Docker access must be mandatory at startup
- Treat Docker socket access as privileged host control and restrict deployment to trusted environments

### Webhook Mode with Reverse Proxy

```bash
docker run -d \
  --name pytmbot \
  --restart on-failure \
  --env TZ="UTC" \
  --volume /etc/pytmbot/config.yaml:/opt/app/pytmbot.yaml:ro \
  --volume /var/run/docker.sock:/var/run/docker.sock:ro \
  --security-opt no-new-privileges \
  --read-only \
  --cap-drop ALL \
  --pid host \
  --memory 256m \
  --cpu-shares 512 \
  orenlab/pytmbot:latest --mode prod --webhook --socket_host 0.0.0.0
```

## Health Checks and Diagnostics

The container includes built-in health checks that monitor:

- Python runtime availability
- Main script health path (`--health_check`)
- Docker socket accessibility and permissions (when mounted)

Run diagnostics:

```bash
# Container health check
docker exec pytmbot ./entrypoint.sh --health_check

# Docker access verification
docker exec pytmbot ./entrypoint.sh --check-docker
```

## Resource Limits and Usage

### Typical Resource Usage

- **Memory**: ~80MB under normal load
- **CPU**: Minimal under normal load
- **Storage**: ~100MB (image size)
- **Network**: Varies based on monitoring interval

### Recommended Limits

| Resource          | Recommended Limit       |
|-------------------|-------------------------|
| Memory            | 256MB (hard limit)      |
| Swap              | 256MB                   |
| CPU shares        | 512 (relative weight)   |
| Processes         | 65535 max               |
| File descriptors  | 20000 soft / 40000 hard |
| Temporary storage | 150MB total (tmpfs)     |

### Performance Tips

- Use `restart: on-failure` instead of `unless-stopped` for better resource management
- Enable log rotation to prevent disk space issues
- Use tmpfs mounts for temporary data

## Upgrading

```bash
# Pull latest image for the bot service
docker compose pull pytmbot

# Recreate containers with the updated image
docker compose up -d pytmbot
```

## Reproducible Builds

Each release image is built in an isolated GitHub Actions environment with pinned dependency versions. The build process
is fully automated and reproducible. The GitHub Action source code is available in the repository.

### Supply Chain Security

All published images include:

- **Provenance attestations** (`mode=max`): cryptographically signed metadata linking each image to its source commit,
  build workflow, and builder identity. Verifiable via `docker buildx imagetools inspect`.
- **SBOM (Software Bill of Materials)**: machine-readable inventory of all packages and dependencies included in the
  image, enabling automated vulnerability scanning and license compliance checks.

Verify provenance for a published image:

```bash
docker buildx imagetools inspect orenlab/pytmbot:latest --format "{{json .Provenance}}"
```

### Build-time Bytecode

Official builds compile Python bytecode during image build to reduce cold-start overhead in production.

- `COMPILE_BYTECODE=1` (default): compile bytecode (faster startup, slightly larger image and longer build).
- `COMPILE_BYTECODE=0`: skip compilation (faster build, slightly slower startup).

CI policy:

- `ubuntu-dev` uses `COMPILE_BYTECODE=0` to keep development images smaller.
- release images use `COMPILE_BYTECODE=1` for faster production startup.

Example:

```bash
docker build --build-arg COMPILE_BYTECODE=0 -t orenlab/pytmbot:local-dev .
```

## Troubleshooting

1. **Configuration errors**:
   ```bash
   docker logs pytmbot
   ```

2. **Permission issues**:
    - Ensure Docker socket has correct permissions
    - Verify configuration file ownership

3. **Network connectivity**:
   ```bash
   docker exec pytmbot python3 -c "import socket; socket.create_connection(('api.telegram.org', 443), 5); print('ok')"
   ```

4. **Memory issues**:
    - Monitor memory usage: `docker stats pytmbot`
    - Adjust memory limits if needed

5. **High CPU usage**:
    - Check log level (reduce from DEBUG to INFO)
    - Verify monitoring intervals in config

6. **Plugin loading issues**:
    - Verify plugin dependencies (InfluxDB for monitor plugin)
    - Check plugin-specific configuration sections

## Development

See our [Contributing Guidelines](https://github.com/orenlab/pytmbot/blob/master/CONTRIBUTING.md) for information on:

- Setting up development environment
- Code style and guidelines
- Pull request process
- Code review requirements

## Support

- [Documentation](https://github.com/orenlab/pytmbot/tree/master/docs)
- [GitHub Discussions](https://github.com/orenlab/pytmbot/discussions)

## License

Released under the [MIT License](https://github.com/orenlab/pytmbot/blob/master/LICENSE).
