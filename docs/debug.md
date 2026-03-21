# Debugging And Diagnostics

This document covers supported diagnostic paths for the current runtime.

## Increase Log Detail

For the Docker image:

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /path/to/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
  orenlab/pytmbot:stable \
  --mode prod --log-level DEBUG
```

For local execution:

```bash
uv run python pytmbot/main.py --mode dev --log-level DEBUG
```

Notes:

- `DEBUG` keeps full stack traces.
- `INFO` and above keep logs concise.
- `--log-format human` is easier for interactive debugging.

## Container Logs

```bash
docker logs pytmbot
docker logs -f pytmbot
```

## Health Diagnostics

Application-level health status:

```bash
uv run python pytmbot/main.py --health_check
```

Docker image diagnostic entrypoint:

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /path/to/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
  orenlab/pytmbot:stable \
  --health_check
```

Docker access validation:

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  orenlab/pytmbot:stable \
  --check-docker
```

## Common Failure Areas

Check these first:

- wrong bot token in `pytmbot.yaml`
- missing allowlist entries in `access_control`
- Docker socket not mounted or inaccessible
- webhook host or port mismatch
- missing `influxdb` config when `monitor` plugin is enabled
- missing `plugins_config.outline` fields when `outline` is enabled

## Useful References

- [settings.md](settings.md)
- [webhook.md](webhook.md)
- [health.md](health.md)
- [release_policy.md](release_policy.md)
- [development.md](development.md)
