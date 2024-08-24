# pyTMBot v.2 installation from GitHub registry

__The methods for setting up the bots v.1 and v.2 are different and cannot be used together!__

## 🧪 Configure bot

1. Secret Settings:

- Let's create the necessary files:

```bash
sudo -i
cd /root/
touch pytmbot.yaml
```

Then,

```bash
nano pytmbot.yaml
```

And we insert the following content, then fill in the required fields between single quotes:

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
  # A script for the fast generation of a truly unique "salt" is available in the bot's repository:
  # https://github.com/orenlab/pytmbot/blob/feature/2.0.0/cli/generate_salt.py
  auth_salt:
    - ''
# Docker settings
docker:
  # Docker socket. Usually: unix:///var/run/docker.sock.
  host:
    - 'unix:///var/run/docker.sock'

```

Then press `Ctrl + X` followed by `Y` to save your changes and exit the `nano` editor.

#### Note about `auth_salt` parameter:

The bot supports random salt generation. To use this feature, it is recommended to run the following command in a
separate terminal window:

```bash
sudo docker run --rm orenlab/pytmbot:0.2.0-alpine-dev --salt true
```

This command will generate a unique "salt" value for you and display it on the screen. The container will then be
automatically deleted.

## 🔌 Run bot

To launch a Docker container:

```bash
sudo docker run -d -m 100M \
-v /var/run/docker.sock:/var/run/docker.sock:ro \
-v /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
--env TZ="Asia/Yekaterinburg" \
--restart=always \
--name=pytmbot \
--pid=host \
--security-opt=no-new-privileges \
ghcr.io/orenlab/pytmbot:master
```

#### Supported logging levels:

| # | Logging levels | Note                                                                                                                                                                  | Args                | 
|---|----------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------|
| 1 | `INFO`         | Balanced logging mode: only the most important information + a short description of errors and exceptions.                                                            | `--log-level=INFO`  |
| 2 | `ERROR`        | Only errors and exceptions are shown. This can be considered a "quiet" mode.                                                                                          | `--log-level=ERROR` | 
| 3 | `DEBUG`        | The most detailed level of logs provides all the information displayed in the previous levels, plus additional details, such as traces and all debugging information. | `--log-level=DEBUG` |

#### Note #1:

_Please don't forget to specify your time zone! You can find a list of available time zones, for
example, [here](https://manpages.ubuntu.com/manpages/trusty/man3/DateTime::TimeZone::Catalog.3pm.html)_

#### Note #2:

_Please don't forget to specify Tag version!_

Now everything is ready for you to use the bot. All you need to do is run the `/start` command in your Telegram app.

## 🏗 Updating the image

In order to update the image to the latest version, please follow these steps:

* Stopping the running pyTMbot container:

```bash
sudo docker stop pytmbot
```

* Deleting an outdated container:

```bash
sudo docker rm /pytmbot
```

* Deleting an outdated image:

```bash
sudo docker rmi pytmbot
```

* Uploading an updated image:

```bash
sudo docker pull ghcr.io/orenlab/pytmbot:latest
```

And we run it in the same way as we would if we had just installed the bot (see the instructions above).

## 🚀 Bot logs

- To access the bot logs, please run the following command in the terminal:

```bash
sudo docker logs pytmbot
```

- Advanced logs and debugging: [debug.md](debug.md)

_Alternatively, if the container is running on your workstation, you can use Docker Desktop._
