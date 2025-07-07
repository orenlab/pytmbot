# 🎛️ PyTMBot Command-Line Arguments

The PyTMBot supports several command-line arguments to customize its behavior. Below is a detailed description of each
argument you can use when starting the bot.

## 🛠️ Arguments

| Argument         | Type   | Default     | Choices                  | Description                                                                                    |
|------------------|--------|-------------|--------------------------|------------------------------------------------------------------------------------------------|
| `--mode`         | `str`  | `prod`      | `dev`, `prod`            | Select the mode of operation for PyTMBot. Use `dev` for development and `prod` for production. |
| `--log-level`    | `str`  | `INFO`      | `DEBUG`, `INFO`, `ERROR` | Set the logging level for the bot. More verbose logs can be helpful during development.        |
| `--webhook`      | `str`  | `False`     | `True`, `False`          | Start the bot in webhook mode. Useful for receiving updates via HTTP callbacks.                |
| `--socket_host`  | `str`  | `127.0.0.1` | N/A                      | Define the host address for the socket to listen on in webhook mode. Default is localhost.     |
| `--plugins`      | `str`  | `""`        | N/A                      | Specify a comma-separated list of plugins to load. Available: `monitor`, `outline`             |
| `--salt`         | `flag` | `False`     | N/A                      | Generate unique salt for using it in TOTP authentication and exit                              |
| `--health_check` | `flag` | `False`     | N/A                      | Perform comprehensive health check and exit                                                    |
| `--check-docker` | `flag` | `False`     | N/A                      | Check Docker socket access and group configuration, then exit                                  |

## 🏥 Health Check & Diagnostic Arguments

### `--health_check`

Performs a comprehensive health check that validates:

- Main script accessibility
- Python interpreter functionality
- Docker socket access (if available)
- Configuration file presence

**Usage:**

```bash
python main.py --health_check
# or in Docker
docker run orenlab/pytmbot:latest --health_check
```

### `--check-docker`

Specifically checks Docker-related configuration:

- Docker socket availability and permissions
- Group membership for Docker access
- Automatic GID adjustment if running as root

**Usage:**

```bash
python main.py --check-docker
# or in Docker
docker run orenlab/pytmbot:latest --check-docker
```

## 📄 Required Configurations

Depending on the command-line arguments you choose, certain configuration settings must be filled out in your
configuration file. Below are the sections you need to complete:

### General Bot Settings (Required)

- **Bot Token Configuration**: Ensure you provide the correct `prod_token` or `dev_bot_token` based on `--mode`
- **Chat ID Configuration**: Set your `global_chat_id` for notifications
- **Access Control Settings**: Specify `allowed_user_ids`, `allowed_admins_ids`, and `auth_salt`

### Webhook Configuration (if using `--webhook True`)

- **webhook_config**: Fill all parameters in the `webhook_config` section
- **Security Note**: Bot cannot run on port 80 for security reasons. Use reverse proxy (e.g., Nginx, Nginx Proxy
  Manager, or Traefik)
- **Host Configuration**: Set `--socket_host 0.0.0.0` when using with reverse proxy

### Plugins Configuration (if using `--plugins`)

#### Monitor Plugin

- **InfluxDB**: Required for Monitor Plugin functionality
- **InfluxDB Settings**: Set the `url`, `token`, `org`, and `bucket` values in configuration
- **Thresholds**: Adjust the threshold values in the `monitor` section of your configuration

#### Outline Plugin

- **API Configuration**: Set the `api_url` and `cert` paths for the Outline API
- **Certificate**: Ensure proper certificate configuration for secure API access

## 🚀 Usage Examples

### Basic Usage

**Development mode with debug logging:**

```bash
python main.py --mode dev --log-level DEBUG
```

**Production mode with specific plugins:**

```bash
python main.py --mode prod --log-level INFO --plugins monitor,outline
```

### Webhook Mode

**Development webhook (with reverse proxy):**

```bash
python main.py --mode dev --webhook True --socket_host 0.0.0.0
```

**Production webhook:**

```bash
python main.py --mode prod --webhook True --socket_host 0.0.0.0 --log-level INFO
```

### Plugin-Specific Usage

**Monitor plugin only:**

```bash
python main.py --plugins monitor
```

**All plugins with debug logging:**

```bash
python main.py --plugins monitor,outline --log-level DEBUG
```

### Utility Commands

**Generate authentication salt:**

```bash
python main.py --salt
```

**Health check:**

```bash
python main.py --health_check
```

**Docker configuration check:**

```bash
python main.py --check-docker
```

## 🐳 Docker Usage Examples

### Standard Docker Run

**Production deployment:**

```bash
docker run -d \
  --name pytmbot \
  --restart on-failure \
  -v /path/to/config.yaml:/opt/app/pytmbot.yaml:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  orenlab/pytmbot:latest --mode prod --log-level INFO
```

**Development with debug:**

```bash
docker run -d \
  --name pytmbot-dev \
  -v /path/to/config.yaml:/opt/app/pytmbot.yaml:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  orenlab/pytmbot:latest --mode dev --log-level DEBUG --plugins monitor
```

### Docker Compose

```yaml
services:
  pytmbot:
    image: orenlab/pytmbot:latest
    container_name: pytmbot
    restart: on-failure
    volumes:
      - /path/to/config.yaml:/opt/app/pytmbot.yaml:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    command: --mode prod --log-level INFO --plugins monitor,outline
```

### Webhook with Docker

```bash
docker run -d \
  --name pytmbot \
  --restart on-failure \
  -p 8080:8080 \
  -v /path/to/config.yaml:/opt/app/pytmbot.yaml:ro \
  orenlab/pytmbot:latest --mode prod --webhook True --socket_host 0.0.0.0
```

## 🛡️ Security Considerations

### Production Deployment

- Always use `--mode prod` for production environments
- Set log level to `INFO` or `ERROR` to avoid sensitive information in logs
- Use `--webhook True` only behind a reverse proxy with proper SSL termination
- Never expose webhook directly to the internet

### Development

- Use `--mode dev` only in development environments
- `--log-level DEBUG` may contain sensitive information
- Development tokens should be separate from production tokens

## 🔧 Process Management

The entrypoint script handles:

- **Graceful shutdown**: Proper SIGTERM handling with 30-second timeout
- **Docker group management**: Automatic GID adjustment for Docker socket access
- **Health monitoring**: Built-in health checks and diagnostics
- **Error handling**: Comprehensive error reporting and validation

## 📋 Troubleshooting

### Common Issues

1. **Docker permission errors**:
   ```bash
   python main.py --check-docker
   ```

2. **Health check failures**:
   ```bash
   python main.py --health_check
   ```

3. **Plugin loading issues**:
    - Verify InfluxDB connection for monitor plugin
    - Check Outline API configuration for outline plugin

4. **Webhook connection issues**:
    - Ensure reverse proxy is properly configured
    - Check `--socket_host` setting
    - Verify webhook configuration in config file

## 📜 Notes

- Ensure that the arguments are provided in the correct format and within the allowed choices
- Plugin dependencies must be properly configured before using `--plugins`
- Health check and Docker check commands will exit after completion
- For webhook mode, proper reverse proxy configuration is essential for security

For any questions or further assistance, feel free to check out the PyTMBot documentation or open an issue in the
repository.

Happy Botting! 🤖