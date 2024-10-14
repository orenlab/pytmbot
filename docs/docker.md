# pyTMbot Docker Image

Welcome to the Docker Hub page for **pyTMbot**! This page provides information about the Docker image for pyTMbot, a
versatile Telegram bot for managing Docker containers and monitoring server status.

## 🐋 Image Overview

- **Image Name:** `orenlab/pytmbot`
- **Tags:**
    - `latest` - The latest stable release image based on Alpine Linux.
    - `0.X.X` - Specific stable release versions based on Alpine Linux.
    - `alpine-dev` - Latest development version based on Alpine Linux.

## 🚀 Quick Start

### Using Docker Compose

1. **Create a `docker-compose.yml` File:**

```yaml
services:

  pytmbot:
    # Lightweight Alpine-based image with dev environment for pyTMbot
    image: orenlab/pytmbot:0.2.0
    container_name: pytmbot
    # Restart the container only on failure for reliability
    restart: on-failure
    # Set timezone for proper timestamp handling
    environment:
      - TZ=Asia/Yekaterinburg
    volumes:
      # Read-only access to Docker socket for container management
      - /var/run/docker.sock:/var/run/docker.sock:ro
      # Read-only bot configuration file to prevent modifications
      - /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro
    # Prevent the process in the container from gaining additional privileges
    security_opt:
      - no-new-privileges
    # Make the container's filesystem read-only to reduce risks of modification or attack
    read_only: true
    # Drop all capabilities to minimize potential attacks
    cap_drop:
      - ALL
    pid: host  # Use the host's PID namespace for monitoring processes (use with caution)
    # Logging
    logging:
      options:
        max-size: "10m"
        max-file: "3"
    # Run command
    command: --plugins monitor  # Bot start parameters
   ```

2. **Start the Container:**

   ```bash
   docker-compose up -d
   ```

### Using Docker CLI

To launch the Docker container directly:

```bash
sudo docker run -d \
-v /var/run/docker.sock:/var/run/docker.sock:ro \
-v /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
--env TZ="Asia/Yekaterinburg" \
--restart=always \
--name=pytmbot \
--pid=host \
--security-opt=no-new-privileges \
orenlab/pytmbot:0.2.0 --plugins monitor
```

## 🗂️ Configuration (pytmbot.yaml)

Before running the bot, configure the `pytmbot.yaml` file with the necessary settings:

```bash
sudo -i
cd /root
touch pytmbot.yaml
nano pytmbot.yaml
```

Here’s a sample configuration:

```yaml
################################################################
# General Bot Settings
################################################################
# Bot Token Configuration
bot_token:
  # Production bot token.
  prod_token:
    - 'YOUR_PROD_BOT_TOKEN'  # Replace with your actual production bot token.
  # Development bot token. Optional for production bot.
  dev_bot_token:
    - 'YOUR_DEV_BOT_TOKEN'    # Replace with your development bot token (if needed).

# Chat ID Configuration
chat_id:
  # Global chat ID. Used for all notifications from the plugin.
  global_chat_id:
    - 'YOUR_CHAT_ID'  # Replace with your actual chat ID for notifications.

# Access Control Settings
access_control:
  # User IDs allowed to access the bot.
  allowed_user_ids:

  # Admin IDs allowed to access the bot.
  allowed_admins_ids:

  # Salt used for generating TOTP (Time-Based One-Time Password) secrets and verifying TOTP codes.
  auth_salt:
    - 'YOUR_AUTH_SALT'  # Replace with the salt for TOTP.

################################################################
# Docker Settings
################################################################
docker:
  # Docker socket. Usually: unix:///var/run/docker.sock.
  host:
    - 'unix:///var/run/docker.sock'  # Path to the Docker socket.
  # Debug Docker client (to many logs in debug mode with enabled Monitor plugin and Docker containers count monitoring)
  debug_docker_client: false

################################################################
# Webhook Configuration
################################################################
webhook_config:
  # Webhook URL
  url:
    - 'YOUR_WEBHOOK_URL'  # Replace with your actual webhook URL.
  # Webhook port
  webhook_port:
    - 443  # Port for external webhook requests.
  local_port:
    - 5001  # Local port for internal requests.
  cert:
    - 'YOUR_CERTIFICATE'  # Path to the SSL certificate (if using HTTPS).
  cert_key:
    - 'YOUR_CERTIFICATE_KEY'  # Path to the SSL certificate's private key (if using HTTPS).

################################################################
# Plugins Configuration
################################################################
plugins_config:
  # Configuration for the Monitor plugin
  monitor:
    # Threshold settings
    tracehold:
      # CPU usage thresholds in percentage
      cpu_usage_threshold:
        - 80  # Threshold for CPU usage.
      # Memory usage thresholds in percentage
      memory_usage_threshold:
        - 80  # Threshold for memory usage.
      # Disk usage thresholds in percentage
      disk_usage_threshold:
        - 80  # Threshold for disk usage.
      # CPU temperature thresholds in degrees Celsius
      cpu_temperature_threshold:
        - 85  # Threshold for CPU temperature.
      # GPU temperature thresholds in degrees Celsius
      gpu_temperature_threshold:
        - 90  # Threshold for GPU temperature.
      # Disk temperature thresholds in degrees Celsius
      disk_temperature_threshold:
        - 60  # Threshold for disk temperature.
    # Maximum number of notifications for each type of overload
    max_notifications:
      - 3  # Maximum number of notifications sent for a single event.
    # Check interval in seconds
    check_interval:
      - 5  # Interval for system status checks.
    # Reset notification count after X minutes
    reset_notification_count:
      - 5  # Time in minutes to reset the notification count.
    # Number of attempts to retry monitoring startup in case of failure
    retry_attempts:
      - 3  # Number of retry attempts.
    # Interval (in seconds) between retry attempts
    retry_interval:
      - 10  # Interval between retry attempts.
    # Monitor Docker images and containers
    monitor_docker: True  # True - Monitor Docker images and containers. False - Do not monitor Docker.

  # Configuration for the Outline plugin
  outline:
    # Outline API settings
    api_url:
      - 'YOUR_OUTLINE_API_URL'  # Replace with your actual Outline API URL.
    # Certificate fingerprint
    cert:
      - 'YOUR_OUTLINE_CERT'  # Replace with the actual path to your certificate.

################################################################
# InfluxDB Settings
################################################################
influxdb:
  # InfluxDB host
  url:
    - 'YOUR_INFLUXDB_URL'  # URL of your InfluxDB server.
  # InfluxDB token
  token:
    - 'YOUR_INFLUXDB_TOKEN'  # Replace with your actual InfluxDB token.
  # InfluxDB organization name
  org:
    - 'YOUR_INFLUXDB_ORG'  # Replace with your actual organization name in InfluxDB.
  # InfluxDB bucket name
  bucket:
    - 'YOUR_INFLUXDB_BUCKET'  # Replace with your actual bucket name in InfluxDB.
  # InfluxDB debug mode
  debug_mode: false  # Set to true to enable debug mode.
```

### 📋 Explanation of Configuration Fields

- **bot_token**: Set your bot tokens here for production and development.
- **access_control**: Define which user IDs have access to the bot and specify admin IDs.
- **auth_salt**: Used for generating TOTP secrets.
- **docker**: Specify the Docker socket for communication.
- **webhook_config**: Configure the webhook server.
- **plugins_config**: Configure the plugins, including thresholds and retry settings for monitoring.
- **influxdb**: Configure the InfluxDB server (required for Monitor Plugin).

**Note on `auth_salt` Parameter:**

The bot supports random salt generation. To generate a unique salt, run the following command in a separate terminal
window:

   ```bash
   sudo docker run --rm orenlab/pytmbot:0.2.0 --salt
   ```

This command will display a unique salt value and delete the container automatically.

Alternatively, you can use the official script to configure the bot to run on a host or inside a Docker container.

```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/orenlab/pytmbot/refs/heads/master/tools/install.sh)"
```

## 🔌 Plugins

**pyTMbot** supports a plugin system to extend its functionality. Plugins are configured in the `pytmbot.yaml` file and
can be enabled via Docker Compose or Docker CLI.

### Supported Plugins

- Extend functionality through custom plugins with simple configuration.
- Support multiple plugins:
    - **Monitor Plugin:** Monitor CPU, memory, temperature _(only for Linux)_, disk usage, and detect changes in Docker
      containers and images. The plugin sends notifications for various monitored parameters, including new containers
      and images, ensuring timely awareness of system status.
    - **2FA Plugin:** Two-factor authentication for added security using QR codes and TOTP.
    - **Outline VPN Plugin:** Monitor your [Outline VPN](https://getoutline.org/) server directly from Telegram.

Refer to [plugins.md](https://github.com/orenlab/pytmbot/blob/master/docs/plugins.md) for more information on adding and
managing plugins.

### How to Enable Plugins

1. **Add Plugin Configuration to `docker-compose.yml`:**

   For multiple plugins:

   ```yaml
   command: --plugins monitor,outline
   ```

2. **Configure Plugins in `pytmbot.yaml`:**

   External plugin configurations should be placed under `plugins_config` in `pytmbot.yaml`.

   For more details on configuring plugins, refer
   to [plugins.md](https://github.com/orenlab/pytmbot/blob/master/docs/plugins.md).

## 🛠️ Updating the Image

To update to the latest image version:

1. **Stop and Remove the Current Container:**

   ```bash
   sudo docker stop pytmbot
   sudo docker rm pytmbot
   ```

2. **Remove the Outdated Image:**

   ```bash
   sudo docker rmi orenlab/pytmbot
   ```

3. **Pull the Latest Image and Start the Container:**

   ```bash
   sudo docker pull orenlab/pytmbot:latest
   docker-compose up -d
   ```

## 👾 Support, source code, questions and discussions

- Support: https://github.com/orenlab/pytmbot/issues
- Source code: [https://github.com/orenlab/pytmbot/](https://github.com/orenlab/pytmbot/)
- Discussions: [https://github.com/orenlab/pytmbot/discussions](https://github.com/orenlab/pytmbot/discussions)

## 📜 License

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)