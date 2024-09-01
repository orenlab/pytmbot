# pyTMBot v.0.2.0

A simple Telegram bot for managing Docker containers and images, and providing basic information about **local**
servers. The bot operates synchronously and does not use webhooks.

[![Production Docker CI](https://github.com/orenlab/pytmbot/actions/workflows/prod-docker-ci.yml/badge.svg)](https://github.com/orenlab/pytmbot/actions/workflows/prod-docker-ci.yml)
![Github last-commit](https://img.shields.io/github/last-commit/orenlab/pytmbot)
![GitHub Release](https://img.shields.io/github/v/release/orenlab/pytmbot)

## 💡 Key Features

### 🐳 Docker Management

*Some features are protected by two-factor authentication in pyTMBot v.0.2*

- Manage containers (start, stop, restart, etc.)
- View the current status of containers (including finished ones)
- Access container logs
- Retrieve information about Docker images

### 🖥️ Local Server Monitoring

- Load average information
- Summary of memory usage (including swap)
- Sensor data
- Summary of process information
- Uptime information
- Basic file system details
- Network connection information

### 🔖 Additional Features

- Check for bot updates with the `/check_bot_updates` command
- Utilizes `Jinja2` for templated responses
- Logs are available in the Docker log aggregator
- Emoji support 😅

For screenshots, see [screenshots.md](https://github.com/orenlab/pytmbot/blob/master/docs/screenshots.md).

## 🐋 pyTMBot Tags

| Tag          | Description                                                                    |
|--------------|--------------------------------------------------------------------------------|
| `latest`     | The latest stable release image, based on Alpine Linux                         |
| `0.X.X`      | Stable release, based on Alpine Linux                                          |
| `alpine-dev` | Latest development version, not guaranteed to be stable, based on Alpine Linux |

## 🧪 Configure the Bot

1. **Create and Configure the Settings File:**

   Create the configuration file:

   ```bash
   sudo -i
   cd /root/
   touch pytmbot.yaml
   ```

   Edit the file:

   ```bash
   nano pytmbot.yaml
   ```

   Add the following content and fill in the required fields:

   ```yaml
   # Setup bot tokens
   bot_token:
     # Production bot token.
     prod_token:
       - ''
     # Development bot token. Not necessary for production.
     dev_bot_token:
       - ''
   # Setup access control
   access_control:
     # IDs of users who can access the bot.
     allowed_user_ids:
       - 0000000000
     # IDs of admins who can manage Docker images and containers.
     allowed_admins_ids:
       - 0000000000
     # Salt for generating TOTP (Time-Based One-Time Password) secrets.
     auth_salt:
       - ''
   # Docker settings
   docker:
     # Docker socket. Usually: unix:///var/run/docker.sock.
     host:
       - 'unix:///var/run/docker.sock'
   ```

   Save and exit the editor (Ctrl + X, Y).

   **Note:** Generate a unique salt for `auth_salt`:

   ```bash
   sudo docker run --rm orenlab/pytmbot:0.2.0-alpine-dev --salt
   ```

   The generated salt will be displayed on the screen.

## 🔌 Run the Bot

To launch the Docker container, use the following command:

```bash
sudo docker run -d -m 100M \
-v /var/run/docker.sock:/var/run/docker.sock:ro \
-v /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
--env TZ="Asia/Yekaterinburg" \
--restart=always \
--name=pytmbot \
--pid=host \
--security-opt=no-new-privileges \
orenlab/pytmbot:0.2.0-alpine-dev
```

### Supported Logging Levels

| # | Level   | Description                                                                       | Argument            |
|---|---------|-----------------------------------------------------------------------------------|---------------------|
| 1 | `INFO`  | Balanced logging with essential information and brief descriptions of errors.     | `--log-level=INFO`  |
| 2 | `ERROR` | Displays only errors and exceptions (quiet mode).                                 | `--log-level=ERROR` |
| 3 | `DEBUG` | Detailed logs including all information from previous levels, plus debug details. | `--log-level=DEBUG` |

**Notes:**

1. Specify your time zone. A list of available time zones can be
   found [here](https://manpages.ubuntu.com/manpages/trusty/man3/DateTime::TimeZone::Catalog.3pm.html).
2. Ensure you specify the correct tag version.

Once the bot is running, use the `/start` command in Telegram to begin using it.

## 🏗 Update the Image

To update to the latest image version:

1. Stop the current container:

   ```bash
   sudo docker stop pytmbot
   ```

2. Remove the outdated container:

   ```bash
   sudo docker rm pytmbot
   ```

3. Remove the outdated image:

   ```bash
   sudo docker rmi orenlab/pytmbot
   ```

4. Pull the latest image:

   ```bash
   sudo docker pull orenlab/pytmbot:latest
   ```

5. Run the updated image using the instructions provided above.

## Bot Logs

To access the bot logs:

```bash
sudo docker logs pytmbot
```

For advanced logging and debugging, see [debug.md](https://github.com/orenlab/pytmbot/blob/master/docs/debug.md).

Alternatively, use Docker Desktop if running on your workstation.

## 💢 Supported Commands

Here is a list of available commands and their descriptions:

| # | Command              | Button               | Description                         |
|---|----------------------|----------------------|-------------------------------------|
| 1 | `/start`             | None                 | Start the bot                       |
| 2 | `/help`              | None                 | Display help information            |
| 3 | `/docker`            | 🐳 Docker            | Manage Docker containers and images |
| 4 | `/containers`        | 🧰 Containers        | View Docker containers              |
| 5 | `/images`            | 🖼️ Images           | View Docker images                  |
| 6 | `/back`              | 🔙 Back to main menu | Return to the main menu             |
| 7 | `/check_bot_updates` | None                 | Check for bot updates               |

## 👾 Support, Source Code, Questions, and Discussions

- Support: [GitHub Issues](https://github.com/orenlab/pytmbot/issues)
- Source Code: [GitHub Repository](https://github.com/orenlab/pytmbot/)
- Discussions: [GitHub Discussions](https://github.com/orenlab/pytmbot/discussions)

## 🧬 Authors

- [@orenlab](https://github.com/orenlab)

## 📜 License

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)