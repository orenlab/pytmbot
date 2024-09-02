# pyTMbot v0.2.0 Plugins

pyTMbot supports a plugin system to extend its functionality. This document provides details about the available plugins
and how to use them.

## Supported Plugins

- **monitor**: Provides real-time monitoring of CPU, memory, and disk usage on the server where pyTMbot is running.
- **outline**: Interacts with the Outline VPN server API, handling operations like managing access keys and updating
  server settings.

## Plugin Usage

Plugins do not require separate installation. To enable a plugin, specify it using the `--plugins` argument when
starting the container.

### Example Usage with Docker Compose

Create a `docker-compose.yml` file with the following configuration:

```yaml
version: '3.8'

services:
  pytmbot:
    image: orenlab/pytmbot:0.2.0-alpine-dev
    container_name: pytmbot
    restart: always
    environment:
      - TZ=Asia/Yekaterinburg
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro
    security_opt:
      - no-new-privileges
    pid: host
    command: --plugins monitor
```

To start the container:

```bash
docker-compose up -d
```

### Adding External Configuration for Plugins

For plugins requiring an external configuration file, add the volume mapping to your `docker-compose.yml` file.

#### Example: Outline Plugin

If using the Outline Plugin with an external configuration file named `o.yaml`, include:

```yaml
version: '3.8'

services:
  pytmbot:
    image: orenlab/pytmbot:0.2.0-alpine-dev
    container_name: pytmbot
    restart: always
    environment:
      - TZ=Asia/Yekaterinburg
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro
      - /root/o.yaml:/opt/app/o.yaml:ro  # Add this line for Outline Plugin
    security_opt:
      - no-new-privileges
    pid: host
    command: --plugins outline
```

For any plugin requiring an external configuration file, use the following volume mapping format:

```yaml
- /path/on/host/plugin_name_conf.yaml:/path/in/container/plugin_name_conf.yaml:ro
```

### Enabling Multiple Plugins

To enable multiple plugins, update the `command` in `docker-compose.yml`. For example, to enable both `monitor` and
`outline` plugins:

```yaml
command: --plugins monitor,outline
```

Then run:

```bash
docker-compose up -d
```

## Plugin Details

### Monitor Plugin

#### Overview

The Monitor Plugin provides real-time monitoring of CPU, memory, and disk usage on the server where pyTMbot is running.
It allows for customizable thresholds and sends alerts to administrators if resource usage exceeds specified limits.

#### Configuration

The Monitor Plugin uses the `config.py` file for internal settings and requires additional configuration in the
`pytmbot.yaml` file:

```yaml
# Setup chat ID
chat_id:
  # Global chat ID. Used by Monitor plugin.
  global_chat_id:
    # Set chat ID for store monitoring messages.
    - '-0000000000'
```

#### Usage

After enabling the plugin, it will monitor resource usage based on the configuration provided. Notifications will be
sent to the specified chat if thresholds are exceeded.

#### Exception Handling

The Monitor Plugin includes error handling to manage configuration and runtime errors. Errors are logged appropriately
to ensure the bot operates smoothly.

#### Customization

At the moment, the Monitor Plugin does not support customization, but it may be added in the future.

### Outline Plugin

#### Overview

The Outline Plugin integrates with the Outline VPN server API to manage access keys, retrieve server information, update
server settings, and monitor data usage.

#### Configuration

The Outline Plugin uses a configuration file to set API credentials and other options. Configuration details are
specified in the `outline_config.py` file.

#### Usage

Enable the plugin to interact with the Outline VPN server. The plugin handles various operations based on the provided
configuration.

#### Exception Handling

The Outline Plugin includes robust error handling for API communication and configuration issues. Errors are logged for
review.

## Future Enhancements

- Additional plugins and features may be added in future updates.
- Ongoing improvements to plugin functionality and stability.

## Authors

- [@orenlab](https://github.com/orenlab)

## License

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)