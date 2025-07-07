# pyTMbot Docker Image

[![Docker Pulls](https://img.shields.io/docker/pulls/orenlab/pytmbot)](https://hub.docker.com/r/orenlab/pytmbot)
[![Image Size](https://img.shields.io/docker/image-size/orenlab/pytmbot/latest)](https://hub.docker.com/r/orenlab/pytmbot)
[![GitHub Release](https://img.shields.io/github/v/release/orenlab/pytmbot)](https://github.com/orenlab/pytmbot/releases)

A secure, lightweight Docker container for pyTMbot - your Telegram-based monitoring and management solution.

## Quick Reference

- **Maintained by**: [OrenLab Team](https://github.com/orenlab)
- **Where to file issues**: [GitHub Issues](https://github.com/orenlab/pytmbot/issues)
- **Supported architectures**: `amd64`, `arm64`
- **Base image**: Alpine Linux
- **Published image artifact details**:
    - **Image**: `orenlab/pytmbot`
    - **Supported tags**:
        - `latest` - Latest stable release
        - `X.Y.Z` - Specific version releases (e.g., `1.2.3`)
        - `alpine-dev` - Development version

## Security Features

- Read-only container filesystem
- Minimal base image (Alpine Linux)
- Regular security updates
- Dropped unnecessary capabilities
- No privilege escalation allowed
- Isolated network with disabled inter-container communication
- Temporary filesystem mounts for security

## Prerequisites

- Docker Engine 20.10+
- Docker Compose v2.0+ (recommended)
- 256MB RAM for optimal performance
- 100MB free disk space
- Internet connection for initial pull

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

## Configuration Requirements

### General Bot Settings (Required)

- **Bot Token**: Provide `prod_token` or `dev_bot_token` depending on mode
- **Chat ID**: Set `global_chat_id` for notifications
- **Access Control**: Configure `allowed_user_ids`, `allowed_admins_ids`, and `auth_salt`

### Webhook Configuration (if using `--webhook True`)

- **webhook_config**: Complete all parameters in the webhook configuration section
- **Security Note**: Bot cannot run on port 80 for security reasons. Use reverse proxy (Nginx, Nginx Proxy Manager, or
  Traefik)

### Plugin-Specific Configuration

- **Monitor Plugin**: Requires InfluxDB connection settings
- **Outline Plugin**: Requires API URL and certificate paths

## Production Deployment

### Security Best Practices

- Use `--mode prod` for production deployments
- Set appropriate log levels (`INFO` or `ERROR` for production)
- Configure webhook mode behind reverse proxy
- Use read-only filesystem and dropped capabilities
- Implement proper network isolation

### Example Production Commands

Standard production deployment:

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
  orenlab/pytmbot:latest --mode prod --log-level INFO
```

Webhook mode with reverse proxy:

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
  orenlab/pytmbot:latest --mode prod --webhook True --socket_host 0.0.0.0
```

### Command Line Arguments

| Argument         | Type   | Default     | Choices                  | Description                                                                                    |
|------------------|--------|-------------|--------------------------|------------------------------------------------------------------------------------------------|
| `--mode`         | `str`  | `prod`      | `dev`, `prod`            | Select the mode of operation for PyTMBot. Use `dev` for development and `prod` for production. |
| `--log-level`    | `str`  | `INFO`      | `DEBUG`, `INFO`, `ERROR` | Set the logging level for the bot. More verbose logs can be helpful during development.        |
| `--webhook`      | `str`  | `False`     | `True`, `False`          | Start the bot in webhook mode. Useful for receiving updates via HTTP callbacks.                |
| `--socket_host`  | `str`  | `127.0.0.1` | N/A                      | Define the host address for the socket to listen on in webhook mode. Default is localhost.     |
| `--plugins`      | `list` | `[]`        | N/A                      | Specify a comma-separated list of plugins to load. Available: monitor, outline                 |
| `--salt`         | `str`  | `False`     | N/A                      | Generate unique salt for using it in TOTP authentication                                       |
| `--health_check` | `str`  | `False`     | `True`, `False`          | Perform comprehensive health check and exit                                                    |
| `--check-docker` | N/A    | N/A         | N/A                      | Check Docker socket access and group configuration, then exit                                  |

## Plugin System

pyTMbot supports various plugins to extend functionality:

### Core Plugins

- **Monitor**: System and Docker container monitoring (requires InfluxDB)
- **Outline**: Outline VPN management and monitoring

### Plugin Configuration Requirements

#### Monitor Plugin

- **InfluxDB**: Required for Monitor Plugin functionality
- **Configuration**: Set `url`, `token`, `org`, and `bucket` values in config
- **Thresholds**: Adjust monitoring threshold values in the `monitor` section

#### Outline Plugin

- **API Configuration**: Set `api_url` and `cert` paths for Outline API access

### Usage Examples

Enable specific plugins:

```bash
docker run ... orenlab/pytmbot:latest --plugins monitor,outline
```

Enable single plugin:

```bash
docker run ... orenlab/pytmbot:latest --plugins monitor
```

Development mode with debug logging:

```bash
docker run ... orenlab/pytmbot:latest --mode dev --log-level DEBUG --plugins monitor
```

Webhook mode (requires reverse proxy):

```bash
docker run ... orenlab/pytmbot:latest --webhook True --socket_host 0.0.0.0
```

### Health Checks and Diagnostics

Container health check:

```bash
docker run ... orenlab/pytmbot:latest --health_check
```

Docker access verification:

```bash
docker run ... orenlab/pytmbot:latest --check-docker
```

## Resource Limits

The container is configured with the following resource limits for optimal performance:

- **Memory**: 256MB (hard limit)
- **CPU**: 512 shares (relative weight)
- **Processes**: 65535 max
- **File descriptors**: 20000 soft / 40000 hard
- **Temporary storage**: 150MB total

## Health Checks

The container includes built-in health checks that monitor:

- Configuration file presence
- Network connectivity
- Core service status

## Upgrading

```bash
# Pull latest version
docker pull orenlab/pytmbot:latest

# Stop current container
docker-compose down

# Start with new version
docker-compose up -d
```

## Reproducible Builds

Each release image is built in an isolated GitHub Actions environment with pinned dependency versions. The build process
is fully automated and reproducible. The GitHub Action source code is available in the repository.

## Troubleshooting

### Common Issues

1. **Configuration errors**:
   ```bash
   docker logs pytmbot
   ```

2. **Permission issues**:
    - Ensure Docker socket has correct permissions
    - Verify configuration file ownership

3. **Network connectivity**:
   ```bash
   docker exec pytmbot ping -c 1 api.telegram.org
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

7. **Docker group permissions**:
   ```bash
   docker exec pytmbot --check-docker
   ```

8. **Container health status**:
   ```bash
   docker exec pytmbot --health_check
   ```

## Performance Optimization

- Use `restart: on-failure` instead of `unless-stopped` for better resource management
- Set appropriate memory and CPU limits
- Use isolated networks for security
- Enable log rotation to prevent disk space issues
- Use tmpfs mounts for temporary data

## Resource Usage

- **Memory**: ~80MB (256MB limit)
- **CPU**: Minimal under normal load
- **Storage**: ~100MB
- **Network**: Varies based on monitoring interval

## Development

See our [Contributing Guidelines](https://github.com/orenlab/pytmbot/blob/master/CONTRIBUTING.md) for information on:

- Setting up development environment
- Code style and guidelines
- Pull request process
- Code review requirements

## Support

- [Documentation](https://github.com/orenlab/pytmbot/docs)
- [GitHub Discussions](https://github.com/orenlab/pytmbot/discussions)

## License

Released under the [MIT License](https://github.com/orenlab/pytmbot/blob/master/LICENSE).