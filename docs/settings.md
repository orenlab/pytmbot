# pyTMbot Configuration Guide 🤖

A comprehensive guide for setting up and configuring pyTMbot - your secure Telegram-based monitoring and management
solution.

## 📋 Quick Start

### 1. Create Telegram Bot

1. Find [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` command
3. Follow instructions and get bot token
4. Save the token - you'll need it for configuration

### 2. Get Required IDs

**Get User ID:**

- Method 1: Send any message to [@userinfobot](https://t.me/userinfobot)
- Method 2: Start your bot and send any message - check logs for user ID

**Get Chat ID:**

- For private chat: use your user ID (positive number)
- For group chat: add [@userinfobot](https://t.me/userinfobot) to group and send any message

### 3. Generate Authentication Salt

```bash
# Generate salt for TOTP authentication
docker run --rm orenlab/pytmbot:latest --salt
```

### 4. Create Configuration File

Create `pytmbot.yaml` configuration file:

```yaml
################################################################
# General Bot Settings
################################################################
# Bot Token Configuration
bot_token:
  # Production bot token (REQUIRED)
  # Get your bot token from @BotFather on Telegram
  prod_token:
    - 'YOUR_PROD_BOT_TOKEN'  # Example: '1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk'

  # Development bot token (OPTIONAL)
  # Use separate bot for testing to avoid conflicts
  dev_bot_token:
    - 'YOUR_DEV_BOT_TOKEN'    # Example: '9876543210:ZYXWVUTSRQPONMLKJIHGFEDCBAzyxwvutsrqp'

# Access Control Settings (REQUIRED)
access_control:
  # User IDs allowed to access the bot (REQUIRED)
  # To get your user ID:
  #   Method 1: Send a message to @userinfobot on Telegram
  #   Method 2: Start your bot and send any message - check logs for user ID
  allowed_user_ids:
    - 123456789    # Replace with actual Telegram user ID (number only)
    - 987654321    # You can add multiple user IDs

  # Admin IDs with elevated permissions (REQUIRED)
  # Admins can access sensitive commands
  allowed_admins_ids:
    - 123456789    # Replace with actual admin Telegram user ID

  # Salt for TOTP (Time-Based One-Time Password) generation (REQUIRED)
  # Generate with: docker run --rm orenlab/pytmbot:latest --salt
  # Or use: openssl rand -hex 32
  # Or use any random 32+ character string
  auth_salt:
    - 'your-secret-random-32-char-salt-here-replace-this-value'

# Chat ID Configuration (REQUIRED)
chat_id:
  # Global chat ID for notifications (REQUIRED)
  # For private chat: use your user ID (positive number)
  # For group chat: use group ID (negative number, starts with -)
  # To get chat ID:
  #   Method 1: For groups - add @userinfobot to group and send any message
  #   Method 2: Start your bot and send message - check logs for chat ID
  global_chat_id:
    - -1001234567890  # Example: group chat ID (negative number)
    # - 123456789     # Alternative: private chat ID (positive number)

################################################################
# Docker Settings (REQUIRED)
################################################################
docker:
  # Docker socket path (REQUIRED)
  # Default for Linux: unix:///var/run/docker.sock
  # For Windows: npipe:////./pipe/docker_engine
  host:
    - 'unix:///var/run/docker.sock'

  # Enable Docker client debug logging (OPTIONAL)
  # WARNING: Produces many logs when monitor plugin is enabled
  debug_docker_client: false  # true or false

################################################################
# Webhook Configuration (OPTIONAL)
################################################################
# Only needed if you want to use webhooks instead of polling
# SECURITY: Bot automatically generates random webhook paths and secret tokens
# for enhanced security against unauthorized access
webhook_config:
  # Webhook URL (REQUIRED if using webhooks)
  # Must be accessible from the internet and have valid SSL
  # Bot will automatically append secure random path like: /webhook/RANDOM_STRING/BOT_TOKEN/
  url:
    - 'your-domain.com'  # Replace with your domain (without https:// and path)

  # External webhook port (REQUIRED if using webhooks)
  webhook_port:
    - 8443  # Standard HTTPS port (recommended)
    # - 8443  # Alternative port (allowed by Telegram)

  # Local application port (REQUIRED if using webhooks)
  # Must be >= 1024 (non-privileged port)
  local_port:
    - 5001  # Internal port for the bot application

  # SSL certificate path (OPTIONAL for HTTPS webhooks)
  cert:
    - '/path/to/your/certificate.pem'  # Replace with actual certificate path

  # SSL private key path (OPTIONAL for HTTPS webhooks)
  cert_key:
    - '/path/to/your/private.key'      # Replace with actual private key path

################################################################
# Plugins Configuration (OPTIONAL)
################################################################
plugins_config:
  # System Monitoring Plugin Configuration
  monitor:
    # Resource usage thresholds (all values in percentage or Celsius)
    tracehold:
      # CPU usage threshold (0-100%)
      cpu_usage_threshold:
        - 80  # Alert when CPU usage exceeds 80%

      # Memory usage threshold (0-100%)
      memory_usage_threshold:
        - 80  # Alert when memory usage exceeds 80%

      # Disk usage threshold (0-100%)
      disk_usage_threshold:
        - 80  # Alert when disk usage exceeds 80%

      # CPU temperature threshold (Celsius)
      cpu_temperature_threshold:
        - 85  # Alert when CPU temperature exceeds 85°C

      # GPU temperature threshold (Celsius)
      gpu_temperature_threshold:
        - 90  # Alert when GPU temperature exceeds 90°C

      # Disk temperature threshold (Celsius)
      disk_temperature_threshold:
        - 60  # Alert when disk temperature exceeds 60°C

    # Maximum notifications before stopping alerts
    max_notifications:
      - 3  # Stop sending alerts after 3 notifications for same issue

    # Check interval in seconds
    check_interval:
      - 5  # Check system status every 5 seconds

    # Reset notification count after X minutes
    reset_notification_count:
      - 5  # Reset notification counter after 5 minutes

    # Retry attempts for failed monitoring
    retry_attempts:
      - 3  # Try 3 times before giving up

    # Interval between retry attempts in seconds
    retry_interval:
      - 10  # Wait 10 seconds between retries

    # Monitor Docker containers and images
    monitor_docker: true  # true = monitor Docker, false = don't monitor

  # Outline VPN Plugin Configuration
  outline:
    # Outline VPN API URL (REQUIRED if using Outline plugin)
    # Get this from your Outline VPN server management interface
    api_url:
      - 'https://your-outline-server.com:12345/api'  # Replace with your API URL

    # Certificate fingerprint (REQUIRED if using Outline plugin)
    # Get this from your Outline VPN server
    cert:
      - 'YOUR_OUTLINE_CERT_FINGERPRINT'  # Replace with actual certificate fingerprint

################################################################
# InfluxDB Settings (OPTIONAL)
################################################################
# Only needed if you want to store monitoring data in InfluxDB
influxdb:
  # InfluxDB server URL (REQUIRED if using InfluxDB)
  url:
    - 'http://localhost:8086'  # Replace with your InfluxDB server URL

  # InfluxDB access token (REQUIRED if using InfluxDB)
  # Generate in InfluxDB web interface: Data > Tokens > Generate Token
  token:
    - 'YOUR_INFLUXDB_TOKEN'  # Replace with your actual InfluxDB token

  # InfluxDB organization name (REQUIRED if using InfluxDB)
  org:
    - 'YOUR_INFLUXDB_ORG'  # Replace with your organization name

  # InfluxDB bucket name (REQUIRED if using InfluxDB)
  bucket:
    - 'YOUR_INFLUXDB_BUCKET'  # Replace with your bucket name

  # InfluxDB debug mode (OPTIONAL)
  debug_mode: false  # true = enable debug logs, false = normal logging
```

## 🐳 Docker Deployment

### Prerequisites

- Docker Engine 20.10+
- Docker Compose v2.0+ (recommended)
- 256MB RAM for optimal performance
- 100MB free disk space
- Internet connection for initial pull

### Docker Compose (Recommended)

Create `docker-compose.yml`:

```yaml
services:
  pytmbot:
    image: orenlab/pytmbot:latest
    container_name: pytmbot
    restart: on-failure
    environment:
      - TZ=UTC  # Set your timezone
    volumes:
      # Read-only access to Docker socket for container management
      - /var/run/docker.sock:/var/run/docker.sock:ro
      # Read-only bot configuration file to prevent modifications
      - ./pytmbot.yaml:/opt/app/pytmbot.yaml:ro
    security_opt:
      - no-new-privileges
    read_only: true  # Make the container's filesystem read-only to reduce risks
    cap_drop:
      - ALL  # Drop all capabilities to minimize attack surfaces
    pid: host  # Use the host's PID namespace for monitoring processes (use with caution)
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
    # Bot start parameters: mode, logging level, and plugins
    command: --mode prod --log-level INFO --plugins monitor,outline

networks:
  pytmbot_network:
    driver: bridge
    driver_opts:
      com.docker.network.bridge.enable_icc: "false"
    ipam:
      driver: default
      config:
        - subnet: 172.20.0.0/16
```

### Start the Container

```bash
# Create and start
docker-compose up -d

# View logs
docker-compose logs -f pytmbot

# Stop
docker-compose down
```

## 🔐 Security Features

### Automatic Security Measures

- **Random webhook paths**: automatic generation of secure URLs
- **Rate limiting**: 10 requests/10 seconds, 5 for 404 errors
- **IP validation**: only Telegram servers allowed
- **Secret token verification**: for webhook requests
- **Automatic IP banning**: after 50 excessive requests
- **Read-only filesystem**: container security
- **Dropped capabilities**: minimal attack surface

### Manual Security Setup

**Generate TOTP Salt:**

```bash
# Generate salt
docker run --rm orenlab/pytmbot:latest --salt

# Alternative method
openssl rand -hex 32
```

**Check Docker Access:**

```bash
# Verify Docker socket access
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock:ro \
  orenlab/pytmbot:latest --check-docker
```

## 🔧 Command Line Arguments

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

## 📊 Plugin System

### Available Plugins

#### Monitor Plugin 📈

**Features:**

- CPU, memory, disk usage monitoring
- Temperature monitoring (Linux)
- Docker container monitoring
- Threshold-based alerts
- InfluxDB integration

**Configuration Requirements:**

- **InfluxDB**: Required for Monitor Plugin functionality
- **Thresholds**: Configure alert thresholds
- **Intervals**: Set monitoring intervals

**Example Configuration:**

```yaml
plugins_config:
  monitor:
    tracehold:
      cpu_usage_threshold: [ 80 ]      # CPU threshold (%)
      memory_usage_threshold: [ 80 ]   # Memory threshold (%)
      disk_usage_threshold: [ 80 ]     # Disk threshold (%)
      cpu_temperature_threshold: [ 85 ]    # CPU temperature (°C)
      gpu_temperature_threshold: [ 90 ]    # GPU temperature (°C)
      disk_temperature_threshold: [ 60 ]   # Disk temperature (°C)
    max_notifications: [ 3 ]        # Max notifications per issue
    check_interval: [ 5 ]           # Check interval (seconds)
    reset_notification_count: [ 5 ] # Reset counter (minutes)
    retry_attempts: [ 3 ]           # Retry attempts
    retry_interval: [ 10 ]          # Retry interval (seconds)
    monitor_docker: true          # Monitor Docker containers

# InfluxDB configuration (required for Monitor plugin)
influxdb:
  url: [ 'http://localhost:8086' ]
  token: [ 'YOUR_INFLUXDB_TOKEN' ]
  org: [ 'YOUR_INFLUXDB_ORG' ]
  bucket: [ 'YOUR_INFLUXDB_BUCKET' ]
```

#### Outline Plugin 🔒

**Features:**

- VPN access key management
- Server statistics retrieval
- Server configuration updates
- Traffic usage monitoring

**Configuration Requirements:**

```yaml
plugins_config:
  outline:
    api_url: [ 'https://your-outline-server.com:12345/api' ]
    cert: [ 'YOUR_OUTLINE_CERT_FINGERPRINT' ]
```

### Plugin Usage Examples

**Enable Multiple Plugins:**

```bash
docker run ... orenlab/pytmbot:latest --plugins monitor,outline
```

**Enable Single Plugin:**

```bash
docker run ... orenlab/pytmbot:latest --plugins monitor
```

**Development Mode:**

```bash
docker run ... orenlab/pytmbot:latest --mode dev --log-level DEBUG --plugins monitor
```

## 🌐 Webhook Configuration

### Standard Deployment

```bash
docker run -d \
  --name pytmbot \
  --restart on-failure \
  --env TZ="UTC" \
  --volume ./pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
  --volume /var/run/docker.sock:/var/run/docker.sock:ro \
  --security-opt no-new-privileges \
  --read-only \
  --cap-drop ALL \
  --pid host \
  --memory 256m \
  --cpu-shares 512 \
  orenlab/pytmbot:latest --mode prod --log-level INFO
```

### Webhook Mode with Reverse Proxy

```bash
docker run -d \
  --name pytmbot \
  --restart on-failure \
  --env TZ="UTC" \
  --volume ./pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
  --volume /var/run/docker.sock:/var/run/docker.sock:ro \
  --security-opt no-new-privileges \
  --read-only \
  --cap-drop ALL \
  --pid host \
  --memory 256m \
  --cpu-shares 512 \
  orenlab/pytmbot:latest --mode prod --webhook True --socket_host 0.0.0.0
```

**Important:** Bot cannot run on port 80 for security reasons. Use reverse proxy (Nginx, Nginx Proxy Manager, or
Traefik).

## 🔍 Diagnostics and Troubleshooting

### Health Checks

**Container Health Check:**

```bash
docker run --rm -v ./pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
  orenlab/pytmbot:latest --health_check
```

**Docker Access Check:**

```bash
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock:ro \
  orenlab/pytmbot:latest --check-docker
```

### Log Analysis

```bash
# View container logs
docker logs pytmbot
    
# Follow logs in real-time
docker logs -f pytmbot
    
# Last 100 lines
docker logs --tail 100 pytmbot
```

### Common Issues and Solutions

**1. Configuration Errors:**

```bash
# Check configuration file syntax
docker run --rm -v ./pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
  orenlab/pytmbot:latest --health_check
```

**2. Permission Issues:**

```bash
# Check file permissions
ls -la pytmbot.yaml
chmod 644 pytmbot.yaml

# Verify Docker socket access
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock:ro \
  orenlab/pytmbot:latest --check-docker
```

**3. Bot Not Responding:**

- Verify bot token is correct
- Check User ID in allowed_user_ids
- Ensure bot has proper permissions
- Check logs for authentication errors

**4. Memory Issues:**

```bash
# Monitor memory usage
docker stats pytmbot

# Check memory limits
docker inspect pytmbot | grep -i memory
```

**5. High CPU Usage:**

- Check log level (reduce from DEBUG to INFO)
- Verify monitoring intervals in config
- Review plugin configurations

## 📝 Minimal Configuration Example

```yaml
# Minimal working configuration
bot_token:
  prod_token:
    - 'YOUR_BOT_TOKEN'

access_control:
  allowed_user_ids:
    - 123456789
  allowed_admins_ids:
    - 123456789
  auth_salt:
    - 'your-generated-salt-here'

chat_id:
  global_chat_id:
    - 123456789  # Your user ID for private chat

docker:
  host:
    - 'unix:///var/run/docker.sock'
```

## 🚀 Production Best Practices

### Resource Management

- **Memory**: Set `mem_limit: 256m` (typical usage ~80MB)
- **CPU**: Use `cpu_shares: 512` for fair scheduling
- **Storage**: Container requires ~100MB disk space
- **Network**: Varies based on monitoring interval

### Security Hardening

- Use `restart: on-failure` instead of `unless-stopped`
- Implement proper network isolation
- Enable log rotation to prevent disk space issues
- Use tmpfs mounts for temporary data
- Regular container updates

### Monitoring

- Enable health checks
- Monitor resource usage
- Set appropriate log levels
- Configure log rotation
- Use InfluxDB for metrics storage