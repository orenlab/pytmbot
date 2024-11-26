# pyTMbot Docker Image

Welcome to the **pyTMbot** Docker Hub page! This guide will walk you through setting up and running pyTMbot step-by-step, ensuring a smooth experience from initial configuration to deployment.

## 🐋 Image Overview

- **Image Name:** `orenlab/pytmbot`
- **Tags:**
  - `latest` - The latest stable release image based on Alpine Linux.
  - `0.X.X` - Specific stable release versions based on Alpine Linux.
  - `alpine-dev` - Latest development version based on Alpine Linux.

## 🚀 Step-by-Step Setup

### 1️⃣ Preparing for Deployment

Before we begin, ensure you have Docker and Docker Compose installed on your system. If not, please refer to the [Docker documentation](https://docs.docker.com/get-docker/) for installation instructions.

### 2️⃣ Generating the Authentication Salt

To securely configure the bot, you'll need a unique salt value for Time-Based One-Time Passwords (TOTP). Run the following command to generate it:

```bash
sudo docker run --rm orenlab/pytmbot:latest --salt
```

Save the generated salt for later use in the `pytmbot.yaml` configuration.

### 3️⃣ Configuring the Bot

Create a `pytmbot.yaml` file to define your bot's settings. Here’s how:

```bash
sudo -i
cd /root
nano pytmbot.yaml
```

#### Example Configuration File

```yaml
# General Bot Settings
bot_token:
  prod_token: ['YOUR_PROD_BOT_TOKEN']  # Replace with your production bot token.
chat_id:
  global_chat_id: ['YOUR_CHAT_ID']  # Replace with your Telegram chat ID.
access_control:
  allowed_user_ids: ['123456789']
  allowed_admins_ids: ['987654321']
auth_salt: ['YOUR_GENERATED_SALT']

# Docker Settings
docker:
  host: ['unix:///var/run/docker.sock']
  debug_docker_client: false

# Plugins Configuration
plugins_config:
  monitor:
    cpu_usage_threshold: [80]
    memory_usage_threshold: [80]
    check_interval: [10]
    retry_attempts: [3]
  outline:
    api_url: ['YOUR_OUTLINE_API_URL']
    cert: ['YOUR_OUTLINE_CERT']
```

Refer to the **Plugins Configuration** section below for additional plugin examples.

### 4️⃣ Creating the `docker-compose.yml` File

Now, create a `docker-compose.yml` file to define the container configuration:

```yaml
services:
  pytmbot:
    image: orenlab/pytmbot:latest
    container_name: pytmbot
    restart: on-failure
    environment:
      - TZ=Asia/Yekaterinburg
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro
    security_opt:
      - no-new-privileges
    read_only: true
    cap_drop:
      - ALL
    pid: host
    logging:
      options:
        max-size: "10m"
        max-file: "3"
    command: --plugins monitor,outline
```

### 5️⃣ Deploying the Container

Start the bot using Docker Compose:

```bash
docker-compose up -d
```

Alternatively, you can launch the container directly with the Docker CLI:

```bash
sudo docker run -d \
-v /var/run/docker.sock:/var/run/docker.sock:ro \
-v /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
--env TZ="Asia/Yekaterinburg" \
--restart=always \
--name=pytmbot \
--pid=host \
--security-opt=no-new-privileges \
orenlab/pytmbot:latest --plugins monitor,outline
```

## 🔌 Plugins Configuration

pyTMbot supports an extensive plugin system to extend its functionality. Below are examples for commonly used plugins:

### Monitor Plugin

The **Monitor Plugin** tracks system metrics and Docker events. Here’s an example configuration:

```yaml
plugins_config:
  monitor:
    cpu_usage_threshold: [80]
    memory_usage_threshold: [80]
    disk_usage_threshold: [85]
    check_interval: [5]
    max_notifications: [3]
    retry_attempts: [3]
    retry_interval: [10]
    monitor_docker: true
```

### Outline VPN Plugin

To monitor your [Outline VPN](https://getoutline.org/), configure the plugin as follows:

```yaml
plugins_config:
  outline:
    api_url: ['YOUR_OUTLINE_API_URL']
    cert: ['YOUR_OUTLINE_CERT']
```

For more detailed plugin configurations, visit the [plugins documentation](https://github.com/orenlab/pytmbot/blob/master/docs/plugins.md).

## 🛠️ Updating the Image

Keep your pyTMbot image up to date by following these steps:

1. **Stop and Remove the Current Container:**

   ```bash
   sudo docker stop pytmbot
   sudo docker rm pytmbot
   ```

2. **Pull the Latest Image:**

   ```bash
   sudo docker pull orenlab/pytmbot:latest
   ```

3. **Restart the Container:**

   ```bash
   docker-compose up -d
   ```

## 👾 Support & Resources

- **Support:** [GitHub Issues](https://github.com/orenlab/pytmbot/issues)
- **Source Code:** [GitHub Repository](https://github.com/orenlab/pytmbot/)
- **Discussions:** [GitHub Discussions](https://github.com/orenlab/pytmbot/discussions)

## 📜 License

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)