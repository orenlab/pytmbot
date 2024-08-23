# pyTMBot v.2 self build guide

## 🔌 Installation

So, to install this project:

```bash
git clone https://github.com/orenlab/pytmbot.git
cd ./pytmbot
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

| Files          | Assignment                                                                                         |
|----------------|----------------------------------------------------------------------------------------------------|
| `pytmbot.yaml` | To store bot settings, including tokens, allowed user ID and paths to the Docker and Podman socket |

You can leave the steps with the default settings by simply pressing "Enter".

## 💰 Run bot

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
orenlab/pytmbot:self-build \
--log-level=INFO --mode=prod
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

Now everything is ready for you to use the bot. All you need to do is run the `/start` command in your Telegram app.

## 🚀 Bot logs

- To access the bot logs, please run the following command in the terminal:

```bash
sudo docker logs pytmbot
```

- Advanced logs and debugging: [debug.md](debug.md)

_Alternatively, if the container is running on your workstation, you can use Docker Desktop._