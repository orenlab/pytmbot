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
sudo docker run -d -m 100M \
-v /var/run/docker.sock:/var/run/docker.sock:ro \
-v /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
--env TZ="Asia/Yekaterinburg" \
--restart=always \
--name=pytmbot \
--pid=host \
--security-opt=no-new-privileges \
orenlab/pytmbot:0.2.0 --plugins monitor
```

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

   External plugin configurations should be placed under `plugins_config` in `pytmbot.yaml`. Example configuration:

   ```yaml
   plugins_config:
     monitor:
       tracehold:
         cpu_usage_threshold:
           - 80
         memory_usage_threshold:
           - 80
         disk_usage_threshold:
           - 80
       max_notifications:
         - 3
       check_interval:
         - 2
       reset_notification_count:
         - 5
       retry_attempts:
         - 3
       retry_interval:
         - 10
     outline:
       api_url:
         - ''
       cert:
         - ''
   ```

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

## 📜 License

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)