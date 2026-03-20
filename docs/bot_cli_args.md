# Command-Line Interface

This document describes the current startup interface.

Source of truth:

- `pytmbot/utils/cli.py`
- `entrypoint.sh`

## Two Entry Points

- Core CLI: `python pytmbot/main.py ...`
- Container entrypoint: `docker run ... orenlab/pytmbot:... ...`

The Docker image wraps the core CLI and adds a few container-specific utility flags.

## Core CLI Arguments

| Argument          | Type              | Default           | Notes                                                    |
|-------------------|-------------------|-------------------|----------------------------------------------------------|
| `--mode`          | `dev` or `prod`   | `prod`            | Runtime mode                                             |
| `--log-level`     | enum              | `INFO`            | `TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `--log-format`    | `human` or `json` | derived from mode | `human` in `dev`, `json` in `prod` if omitted            |
| `--colorize_logs` | boolean           | `true`            | Applies to human log output                              |
| `--webhook`       | boolean           | `false`           | Core CLI requires an explicit value                      |
| `--socket_host`   | string            | `127.0.0.1`       | Listener host for webhook mode                           |
| `--plugins`       | list              | empty             | Example: `--plugins monitor outline`                     |
| `--health_check`  | flag              | `false`           | Runs the app health check and exits                      |
| `--debug`         | flag              | `false`           | Forces `--mode dev --log-level DEBUG`                    |

Accepted boolean forms in the core CLI:

- `true`, `false`
- `1`, `0`
- `yes`, `no`
- `on`, `off`

Matching is case-insensitive.

## Docker Entrypoint Additions

The Docker image accepts all arguments above and also adds:

| Argument         | Type | Behavior                                |
|------------------|------|-----------------------------------------|
| `--salt`         | flag | Generates a TOTP salt and exits         |
| `--check-docker` | flag | Verifies Docker socket access and exits |

Entrypoint difference for `--webhook`:

- `python pytmbot/main.py --webhook true`
- `docker run ... --webhook`
- `docker run ... --webhook true`

The container entrypoint accepts both the bare flag and an explicit boolean value.

## Behavioral Notes

- `--debug` overrides `--mode` and `--log-level`.
- Plugin names are validated before startup continues.
- If webhook startup fails, the runtime falls back to polling.
- At `INFO` and above, errors are logged without full Python tracebacks.
- Full tracebacks are kept in `DEBUG`.

## Examples

Local development:

```bash
python pytmbot/main.py --mode dev --log-level DEBUG
```

Local webhook run:

```bash
python pytmbot/main.py --mode prod --webhook true --socket_host 0.0.0.0
```

Production container with plugins:

```bash
docker run -d \
  --name pytmbot \
  -v /path/to/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  orenlab/pytmbot:latest --mode prod --plugins monitor outline
```

Generate a TOTP salt:

```bash
docker run --rm orenlab/pytmbot:latest --salt
```

Check Docker access inside the image:

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  orenlab/pytmbot:latest --check-docker
```

## Related Docs

- [installation.md](installation.md)
- [docker.md](docker.md)
- [settings.md](settings.md)
- [health.md](health.md)
