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

## Supply Chain Security

pyTMbot follows modern software supply chain security practices, with each release image providing:

### Software Bill of Materials (SBOM)

The SBOM provides a complete inventory of all components and dependencies in the image:

```bash
# Get SBOM in SPDX format
docker buildx imagetools inspect orenlab/pytmbot:latest \
  --format "{{ json .SBOM.SPDX }}" > sbom.spdx.json

# Get SBOM in CycloneDX format
docker buildx imagetools inspect orenlab/pytmbot:latest \
  --format "{{ json .SBOM.CycloneDX }}" > sbom.cyclonedx.json
```

### SLSA Provenance

The Provenance attestation contains cryptographically signed build information including:

- Source code and its hash
- Build timestamp and location
- Tools and versions used

To verify Provenance:

```bash
# Get Provenance attestation
docker buildx imagetools inspect orenlab/pytmbot:latest \
  --format "{{ json .Provenance }}" > provenance.json

# Verify signature using cosign
cosign verify-attestation orenlab/pytmbot:latest
```

### Image Verification

Release images are signed using cosign. Verify the signature:

```bash
# Install cosign if not installed
brew install cosign  # macOS
# or
sudo apt-get install cosign  # Ubuntu

# Verify image signature
cosign verify orenlab/pytmbot:latest
```

## Prerequisites

- Docker Engine 20.10+
- Docker Compose v2.0+ (optional)
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
  --restart unless-stopped \
  --env TZ="UTC" \
  --volume /etc/pytmbot/config.yaml:/opt/app/pytmbot.yaml:ro \
  --volume /var/run/docker.sock:/var/run/docker.sock:ro \
  --security-opt no-new-privileges \
  --read-only \
  --cap-drop ALL \
  --pid host \
  orenlab/pytmbot:latest
```

## Docker Compose Usage

```yaml
services:
  pytmbot:
    image: orenlab/pytmbot:latest
    container_name: pytmbot
    restart: unless-stopped
    environment:
      - TZ=UTC
    volumes:
      - /etc/pytmbot/config.yaml:/opt/app/pytmbot.yaml:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    security_opt:
      - no-new-privileges
    read_only: true
    cap_drop:
      - ALL
    pid: host
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

## Configuration

### Environment Variables

| Variable | Description          | Default |
|----------|----------------------|---------|
| `TZ`     | Container timezone   | `UTC`   |

### Volume Mounts

| Path                    | Purpose                                |
|-------------------------|----------------------------------------|
| `/opt/app/pytmbot.yaml` | Main configuration file                |
| `/var/run/docker.sock`  | Docker socket for container monitoring |

## Plugin System

pyTMbot supports various plugins to extend functionality:

### Core Plugins

- **Monitor**: System and Docker container monitoring
- **Outline**: Outline VPN management and monitoring

Enable plugins via command line argument:

```bash
docker run ... orenlab/pytmbot:latest --plugins monitor,outline
```

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
docker stop pytmbot
docker rm pytmbot

# Start new container
docker run ... # (use same run command as above)
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

## Resource Usage

- **Memory**: ~80MB
- **CPU**: Minimal
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
