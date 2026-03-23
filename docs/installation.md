# Installation

This project supports Docker and Docker Compose only.

Source of truth:

- `Dockerfile`
- `entrypoint.sh`
- `pytmbot.yaml.sample`

## Prerequisites

- Docker Engine `20.10+`
- Docker Compose `v2+` recommended
- Telegram bot token from `@BotFather`
- Telegram user ID and target chat ID

## Step 1: Prepare Configuration

Start from the repository sample:

```bash
cp pytmbot.yaml.sample pytmbot.yaml
```

Fill at least these sections:

- `bot_token.prod_token`
- `access_control.allowed_user_ids`
- `access_control.allowed_admins_ids`
- `access_control.auth_salt`
- `chat_id.global_chat_id`
- `docker.host`

Generate the TOTP salt with:

```bash
docker run --rm orenlab/pytmbot:stable --salt
```

## Step 2: Start The Bot

Minimal polling deployment:

```bash
docker run -d \
  --name pytmbot \
  --restart on-failure \
  -v "$(pwd)/pytmbot.yaml:/opt/app/pytmbot.yaml:ro" \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  orenlab/pytmbot:stable --mode prod
```

The default runtime mode is polling. No webhook settings are required for this path.

## Step 3: Verify Startup

Check container logs:

```bash
docker logs -f pytmbot
```

Expected result:

- configuration loads successfully
- bot starts polling or webhook mode
- no validation or access errors are reported

## Docker Compose

Minimal Compose example:

```yaml
services:
  pytmbot:
    image: orenlab/pytmbot:stable
    container_name: pytmbot
    restart: on-failure
    volumes:
      - ./pytmbot.yaml:/opt/app/pytmbot.yaml:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    command: --mode prod
```

## Optional Features

- Webhook mode: configure `webhook_config` and start with `--webhook true`
- Plugins: enable with `--plugins ...`
- Monitor plugin: also requires `influxdb`

## Related Docs

- [settings.md](settings.md)
- [docker.md](docker.md)
- [release_policy.md](release_policy.md)
- [bot_cli_args.md](bot_cli_args.md)
- [webhook.md](webhook.md)
