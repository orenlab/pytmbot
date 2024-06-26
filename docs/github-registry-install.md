# pyTMBot installation from GitHub registry

## 🔌 Installation

```bash
sudo docker pull ghcr.io/orenlab/pytmbot:latest
```

## 🧪 Configure bot

1. Secret Settings:

- Let's create the necessary files:

```bash
sudo -i
cd /root/
touch .pytmbotenv
```

Then,

```bash
nano .pytmbotenv
```

And we insert the following content, first replacing `<PUT YOUR VALUE HERE>`:

```bash
# The bot token that you received from the BotFather:
BOT_TOKEN=<PUT YOUR VALUE HERE>
# Add your telegram IDs:
ALLOWED_USER_IDS=[00000000000, 00000000000]
# Set Docker Socket o TCP param. Usually: unix:///var/run/docker.sock: 
DOCKER_HOST='unix:///var/run/docker.sock'
```

Then press `Ctrl + X` followed by `Y` to save your changes and exit the `nano` editor.

## 🔌 Run bot

To launch a Docker container:

```bash
sudo docker run -d -m 100M \
-v /var/run/docker.sock:/var/run/docker.sock:ro \
-v /root/.pytmbotenv:/opt/pytmbot/.pytmbotenv:ro \
--env TZ="Asia/Yekaterinburg" \
--restart=always \
--name=pytmbot \
--pid=host \
--security-opt=no-new-privileges \
ghcr.io/orenlab/pytmbot:latest
```

##### **Note:**

_Please don't forget to specify your time zone! You can find a list of available time zones, for
example, [here](https://manpages.ubuntu.com/manpages/trusty/man3/DateTime::TimeZone::Catalog.3pm.html)_

##### **Note:**

_Please don't forget to specify Tag version!_

Now everything is ready for you to use the bot. All you need to do is run the `/start` command in your Telegram app.

## 🏗 Updating the image

In order to update the image to the latest version, please follow these steps:

* Stopping the container:

```bash
sudo docker stop pytmbot
```

* Deleting an outdated image:

```bash
sudo docker rm pytmbot
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
