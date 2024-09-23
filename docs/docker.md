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
   version: '3.8'

   services:
     pytmbot:
       image: orenlab/pytmbot:0.2.0
       container_name: pytmbot
       restart: always
       environment:
         - TZ=Asia/Yekaterinburg
       volumes:
         - /var/run/docker.sock:/var/run/docker.sock:ro
         - /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro
       security_opt:
         - no-new-privileges
       pid: host
       command: --plugins monitor
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
# Setup bot tokens
bot_token:
  # Prod bot token.
  prod_token:
    - ''
  # Development bot token. Not necessary for production bot.
  dev_bot_token:
    - ''
# Setup access control
access_control:
  # The ID of the users who have permission to access the bot.
  # You can have one or more values - there are no restrictions.
  allowed_user_ids:
    - 0000000000
    - 0000000000
  # The ID of the admins who have permission to access the bot.
  # You can have one or more values, there are no restrictions.
  # However, it's important to keep in mind that these users will be able to manage Docker images and containers.
  allowed_admins_ids:
    - 0000000000
    - 0000000000
  # Salt is used to generate TOTP (Time-Based One-Time Password) secrets and to verify the TOTP code.
  # A script for the fast generation of a truly unique "salt" is available in the bot's repository.
  auth_salt:
    - ''
# Docker settings
docker:
  # Docker socket. Usually: unix:///var/run/docker.sock.
  host:
    - 'unix:///var/run/docker.sock'
# Plugins configuration
plugins_config:
  # Configuration for Monitor plugin
  monitor:
    # Tracehold settings
    tracehold:
      # CPU usage thresholds in percentage
      cpu_usage_threshold:
        - 80
      # Memory usage thresholds in percentage
      memory_usage_threshold:
        - 80
      # Disk usage thresholds in percentage
      disk_usage_threshold:
        - 80
      # CPU temperature thresholds in Celsius
      cpu_temperature_threshold:
        - 85
      # GPU temperature thresholds in Celsius
      gpu_temperature_threshold:
        - 90
      # Disk temperature thresholds in Celsius
      disk_temperature_threshold:
        - 60
    # Number of notifications to send for each type of overload
    max_notifications:
      - 3
    # Check interval in seconds
    check_interval:
      - 2
    # Reset notification count after X minutes
    reset_notification_count:
      - 5
    # Number of attempts to retry starting monitoring in case of failure
    retry_attempts:
      - 3
    # Interval (in seconds) between retry attempts
    retry_interval:
      - 10
  # Configuration for Outline plugin
  outline:
    # Outline API settings
    api_url:
      - ''
    cert:
      - ''
```

### 📋 Explanation of Configuration Fields

- **bot_token**: Set your bot tokens here for production and development.
- **access_control**: Define which user IDs have access to the bot and specify admin IDs.
- **auth_salt**: Used for generating TOTP secrets.
- **docker**: Specify the Docker socket for communication.
- **plugins_config**: Configure the plugins, including thresholds and retry settings for monitoring.

**Note on `auth_salt` Parameter:**

  The bot supports random salt generation. To generate a unique salt, run the following command in a separate terminal
  window:

   ```bash
   sudo docker run --rm ghcr.io/orenlab/pytmbot:latest --salt
   ```

  This command will display a unique salt value and delete the container automatically.

## 🔌 Plugins

**pyTMbot** supports a plugin system to extend its functionality. Plugins are configured in the `pytmbot.yaml` file and
can be enabled via Docker Compose or Docker CLI.

### Supported Plugins

- **Monitor**: Provides real-time monitoring of CPU, memory, and disk usage on the server.
- **Outline**: Interacts with the Outline VPN server API for managing access keys and updating server settings.

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