# pyTMBot v.0.2.0

**pyTMbot** is a flexible Telegram bot designed to manage Docker containers, monitor server status, and extend its
functionality through a plugin system. The bot operates synchronously without the need for webhooks.

[![Production Docker CI](https://github.com/orenlab/pytmbot/actions/workflows/prod-docker-ci.yml/badge.svg)](https://github.com/orenlab/pytmbot/actions/workflows/prod-docker-ci.yml)
![Github last-commit](https://img.shields.io/github/last-commit/orenlab/pytmbot)
![GitHub Release](https://img.shields.io/github/v/release/orenlab/pytmbot)

## 💡 Key Features

### 🐳 Docker Management

*Some features are protected by two-factor authentication in pyTMBot v.0.2*

- **Container Management:** Start, stop, restart, and manage containers.
- **Status Monitoring:** View current and finished container statuses.
- **Log Access:** Retrieve container logs.
- **Image Information:** Get details about Docker images.

### 🖥️ Local Server Monitoring

- **Load Average:** Monitor server load averages.
- **Memory Usage:** View memory and swap usage summaries.
- **Sensor Data:** Access sensor data.
- **Process Information:** Summarize process details.
- **Uptime:** Check system uptime.
- **File System Details:** View basic file system information.
- **Network Information:** Get network connection details.

### 🔖 Additional Features

- **Bot Updates:** Check for updates with the `/check_bot_updates` command.
- **Templated Responses:** Utilize `Jinja2` for responses.
- **Logging:** Logs are available in the Docker log aggregator.
- **Emoji Support:** Enjoy emoji support 😅

For screenshots, visit [screenshots.md](https://github.com/orenlab/pytmbot/blob/master/docs/screenshots.md).

## 🐋 pyTMBot Tags

| Tag          | Description                                                                    |
|--------------|--------------------------------------------------------------------------------|
| `latest`     | Latest stable release image, based on Alpine Linux                             |
| `0.X.X`      | Stable release, based on Alpine Linux                                          |
| `alpine-dev` | Latest development version, not guaranteed to be stable, based on Alpine Linux |

## 🧪 Configuration

### 1. Create and Configure the Settings File

1. **Create the Configuration File:**

   ```bash
   sudo -i
   cd /root/
   touch pytmbot.yaml
   ```

2. **Edit the File:**

   ```bash
   nano pytmbot.yaml
   ```

   Add the following content and fill in the required fields:

   ```yaml
   # Setup bot tokens
   bot_token:
     # Prod bot token.
     prod_token:
       - ''
     # Development bot token. Not necessary for production bot.
     dev_bot_token:
       - ''
   # Setup chat ID
   chat_id:
     # Global chat ID. Used Monitor plugin.
     global_chat_id:
       - '-00000000000'
   # Setup access control
   access_control:
     # The ID of the users who have permission to access the bot.
     # You can have one or more values - there are no restrictions.
     allowed_user_ids:
       - 00000000000
     # The ID of the admins who have permission to access the bot.
     # You can have one or more values, there are no restrictions.
     # However, it's important to keep in mind that these users will be able to manage Docker images and containers.
     allowed_admins_ids:
       - 00000000000
     # Salt is used to generate TOTP (Time-Based One-Time Password) secrets and to verify the TOTP code.
     # A script for the fast generation of a truly unique "salt" is available in the bot's repository.
     auth_salt:
       - ''
   # Docker settings
   docker:
     # Docker socket. Usually: unix:///var/run/docker.sock.
     host:
       - 'unix:///var/run/docker.sock'
   ```

   Save and exit the editor (Ctrl + X, Y).

3. **Generate a Unique Salt:**

   ```bash
   sudo docker run --rm orenlab/pytmbot:0.2.0-alpine-dev --salt
   ```

   The generated salt will be displayed on the screen.

## 🔌 Running the Bot

### Using Docker Compose

1. **Create a `docker-compose.yml` File:**

   ```yaml
   version: '3.8'

   services:
     pytmbot:
       image: orenlab/pytmbot:0.2.0-alpine-dev
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

### Using Docker CLI (For Reference)

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
orenlab/pytmbot:0.2.0-alpine-dev --plugins monitor
```

## 🧩 Plugin Configuration

To use plugins with `pyTMBot`, you need to configure them in the `docker-compose.yml` file or Docker CLI command.

1. **Add Plugin Configuration:**

   For plugins requiring an external configuration file:

   ```yaml
   volumes:
     - /root/some_external_config.yaml:/opt/app/some_external_config.yaml:ro
   command: --plugins some_plugin
   ```

   Update the `docker-compose.yml` file accordingly.

2. **Run with Multiple Plugins:**

   ```yaml
   command: --plugins monitor,outline
   ```

## 🏗 Updating the Image

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

## 🗒 Logs

To view bot logs:

```bash
sudo docker logs pytmbot
```

For advanced logging and debugging, see [debug.md](https://github.com/orenlab/pytmbot/blob/master/docs/debug.md).

## 💢 Supported Commands

| Command              | Description                         |
|----------------------|-------------------------------------|
| `/start`             | Start the bot                       |
| `/help`              | Display help information            |
| `/docker`            | Manage Docker containers and images |
| `/containers`        | View Docker containers              |
| `/images`            | View Docker images                  |
| `/back`              | Return to the main menu             |
| `/check_bot_updates` | Check for bot updates               |

## 👾 Support and Resources

- **Support:** [GitHub Issues](https://github.com/orenlab/pytmbot/issues)
- **Source Code:** [GitHub Repository](https://github.com/orenlab/pytmbot/)
- **Discussions:** [GitHub Discussions](https://github.com/orenlab/pytmbot/discussions)

## 🧬 Authors

- [@orenlab](https://github.com/orenlab)

## 📜 License

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)