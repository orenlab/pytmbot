# pyTMBot v.2 Installation from GitHub Registry

**Note: The setup methods for pyTMBot v.1 and v.2 are different and cannot be used interchangeably.**

## 🧪 Configure the Bot

1. **Create and Configure the Settings File:**

    - Switch to the root user and create the configuration file:

      ```bash
      sudo -i
      cd /root/
      touch pytmbot.yaml
      ```

    - Open the file with a text editor:

      ```bash
      nano pytmbot.yaml
      ```

    - Insert the following content into `pytmbot.yaml`, and fill in the required fields between single quotes:

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
        # User IDs with access to the bot.
        allowed_user_ids:
          - 0000000000
          - 0000000000
        # Admin IDs with access to manage Docker images and containers.
        allowed_admins_ids:
          - 0000000000
          - 0000000000
        # Salt for generating TOTP secrets and verification.
        # Generate a unique salt using the provided script.
        auth_salt:
          - ''
      # Docker settings
      docker:
        # Docker socket. Usually: unix:///var/run/docker.sock.
        host:
          - 'unix:///var/run/docker.sock'
      ```

    - Save and exit the editor by pressing `Ctrl + X`, then `Y`.

   **Note on `auth_salt` Parameter:**

   The bot supports random salt generation. To generate a unique salt, run the following command in a separate terminal
   window:

   ```bash
   sudo docker run --rm ghcr.io/orenlab/pytmbot:latest --salt
   ```

This command will display a unique salt value and delete the container automatically.

## 🔌 Run the Bot

To start the bot in a Docker container, use the following command:

```bash
sudo docker run -d -m 100M \
-v /var/run/docker.sock:/var/run/docker.sock:ro \
-v /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
--env TZ="Asia/Yekaterinburg" \
--restart=always \
--name=pytmbot \
--pid=host \
--security-opt=no-new-privileges \
ghcr.io/orenlab/pytmbot:latest
```

### Supported Logging Levels

| # | Logging Level | Description                                                                                           | Argument            |
|---|---------------|-------------------------------------------------------------------------------------------------------|---------------------|
| 1 | `INFO`        | Provides essential information and brief descriptions of errors and exceptions.                       | `--log-level=INFO`  |
| 2 | `ERROR`       | Displays only errors and exceptions, offering a quieter mode.                                         | `--log-level=ERROR` |
| 3 | `DEBUG`       | Shows detailed logs including all information from previous levels plus additional debugging details. | `--log-level=DEBUG` |

#### Note #1:

- **Time Zone**: Specify your time zone. A list of available time zones can be
  found [here](https://manpages.ubuntu.com/manpages/trusty/man3/DateTime::TimeZone::Catalog.3pm.html).

#### Note #2:

- **Tag Version**: Ensure you specify the correct tag version for the Docker image.

Once the bot is running, use the `/start` command in your Telegram app to initialize it.

## 🏗 Updating the Image

To update to the latest version of the image, follow these steps:

1. Stop the running container:

    ```bash
    sudo docker stop pytmbot
    ```

2. Remove the outdated container:

    ```bash
    sudo docker rm pytmbot
    ```

3. Remove the outdated image:

    ```bash
    sudo docker rmi ghcr.io/orenlab/pytmbot:latest
    ```

4. Pull the updated image:

    ```bash
    sudo docker pull ghcr.io/orenlab/pytmbot:latest
    ```

5. Re-run the container using the instructions provided above.

## 🚀 Bot Logs

To view the bot logs, execute the following command:

```bash
sudo docker logs pytmbot
```

For advanced logging and debugging details, refer to [debug.md](debug.md).

Alternatively, if the container is running on your workstation, you can use Docker Desktop to view the logs.