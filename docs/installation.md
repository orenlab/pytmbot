# pyTMBot installation and setup guide

## 🔌 Installation

There are two ways for today:

1. Use a pre-build bot image. Then, please follow
   the [instructions](https://hub.docker.com/r/orenlab/pytmbot) posted on the Docker Hub.
2. Assemble the image of the bot yourself. This guide is about this method

So, to install this project:

```bash
git clone https://github.com/orenlab/pytmbot.git
cd ~/pytmbot
```

## 🧪 Configure bot

1. Activate the virtual environment and install the dependencies for the bot configuration script using your preferred
   package manager. The following instructions provide an example using pip.
   (__mandatory stage__):

```bash
python -m venv .venv
source ~/pytmbot/.venv/bin/activate
pip install -r setup_req.txt
```

2. Run the CLI Setup Wizard (__mandatory stage__):

```bash
python3 ./setup_bot.py
```

And follow the wizard's instructions.

This wizard will generate the necessary configuration file for you:

| Files       | Assignment                                                                                         |
|-------------|----------------------------------------------------------------------------------------------------|
| .pytmbotenv | To store bot settings, including tokens, allowed user ID and paths to the Docker and Podman socket |

You can leave the steps with the default settings by simply pressing "Enter".

## 💰 Run bot

To build a Docker image:

```bash
cd ~/pytmbot

# To launch with a production token. Default way:
docker --target selfbuild_prod build -t orenlab/pytmbot:latest .

# To launch with a development token. Only for development:
docker --target selfbuild_dev build -t orenlab/pytmbot:latest .
```

To launch a Docker container:

```bash
sudo docker run -d -m 100M \
-v /var/run/docker.sock:/var/run/docker.sock:ro \
--env TZ="Asia/Yekaterinburg" \
--restart=always \
--name=pytmbot \
--pid=host \
--security-opt=no-new-privileges \
orenlab/pytmbot:latest
```

##### **Note**

_Please don't forget to specify your time zone! You can find a list of available time zones, for
example, [here](https://manpages.ubuntu.com/manpages/trusty/man3/DateTime::TimeZone::Catalog.3pm.html)_

Docker image size ~70 Mb.

Now everything is ready for you to use the bot. All you need to do is run the `/start` command in your Telegram app.

## 🚀 Bot logs

- To access the bot logs, please run the following command in the terminal:

```bash
sudo docker logs pytmbot
```

_Alternatively, if the container is running on your workstation, you can use Docker Desktop._
