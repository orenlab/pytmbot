# pyTMbot Plugins 🌟

pyTMbot supports a plugin system to extend the bot's functionality. This document describes the available plugins and
how to configure them.

## 🧩 Supported Plugins

- **monitor**: Provides real-time monitoring of CPU, memory, temperature _(only on Linux)_, and disk usage on the server
  where pyTMbot is running.
- **outline**: Interacts with the Outline VPN server API, allowing for access key management and server settings
  updates.

## ⚙️ Plugin Usage

Plugins do not require separate installation. To enable a plugin, specify it using the `--plugins` argument when
starting the container.

### 🐳 Example Usage with Docker Compose

Create a `docker-compose.yml` file with the following configuration:

```yaml
services:

  pytmbot:
    # Lightweight Alpine-based image with dev environment for pyTMbot
    image: orenlab/pytmbot:alpine-dev
    container_name: pytmbot
    # Restart the container only on failure for reliability
    restart: on-failure
    # Set timezone for proper timestamp handling
    environment:
      - TZ=Asia/Yekaterinburg
    volumes:
      # Read-only access to Docker socket for container management
      - /var/run/docker.sock:/var/run/docker.sock:ro
      # Read-only bot configuration file to prevent modifications
      - /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro
    # Prevent the process in the container from gaining additional privileges
    security_opt:
      - no-new-privileges
    # Make the container's filesystem read-only to reduce risks of modification or attack
    read_only: true
    # Drop all capabilities to minimize potential attacks
    cap_drop:
      - ALL
    pid: host  # Use the host's PID namespace for monitoring processes (use with caution)
    # Logging
    logging:
      options:
        max-size: "10m"
        max-file: "3"
    # Run command
    command: --plugins monitor,outline --log-level DEBUG  # Bot start parameters: logging, and plugins
```

To start the container:

```bash
docker-compose up -d
```

### 🔧 External Configuration for Plugins

Plugin configurations are stored in the `pytmbot.yaml` file under the `plugins_config` section.

#### Example: Monitor Plugin Configuration

For the Monitor Plugin, the thresholds and other settings are defined in the `pytmbot.yaml` file. Example:

```yaml
plugins_config:
  # Configuration for Monitor plugin
  monitor:
    # Tracehold settings
    tracehold:
      # CPU usage thresholds in percentage
      cpu_usage_threshold:
        - 80
      # Memory usage thresholds in percentage
      memory_usage_threshold:
        - 80
      # Disk usage thresholds in percentage
      disk_usage_threshold:
        - 80
      # CPU temperature thresholds in Celsius
      cpu_temperature_threshold:
        - 85
      # GPU temperature thresholds in Celsius
      gpu_temperature_threshold:
        - 90
      # Disk temperature thresholds in Celsius
      disk_temperature_threshold:
        - 60
    # Number of notifications to send for each type of overload
    max_notifications:
      - 3
    # Check interval in seconds
    check_interval:
      - 7
    # Reset notification count after X minutes
    reset_notification_count:
      - 5
    # Number of attempts to retry starting monitoring in case of failure
    retry_attempts:
      - 3
    # Interval (in seconds) between retry attempts
    retry_interval:
      - 10
    # Enable Docker images and containers count monitoring
    monitor_docker: True
```

For Monitor Plugin required `InfluxDB` (recommended run in Docker Container) settings are defined in the `pytmbot.yaml`
file. Example:

```yaml
################################################################
# InfluxDB Settings
################################################################
influxdb:
  # InfluxDB host
  url:
    - 'YOUR_INFLUXDB_URL'  # URL of your InfluxDB server.
  # InfluxDB token
  token:
    - 'YOUR_INFLUXDB_TOKEN'  # Replace with your actual InfluxDB token.
  # InfluxDB organization name
  org:
    - 'YOUR_INFLUXDB_ORG'  # Replace with your actual organization name in InfluxDB.
  # InfluxDB bucket name
  bucket:
    - 'YOUR_INFLUXDB_BUCKET'  # Replace with your actual bucket name in InfluxDB.
  # InfluxDB debug mode
  debug_mode: false  # Set to true to enable debug mode.
```

### Outline Plugin Configuration

The configuration for the Outline Plugin is also stored in the `plugins_config` section of the `pytmbot.yaml` file.
Example:

```yaml
plugins_config:
  outline:
    api_url:
      - 'https://your-outline-server.com'
    cert:
      - 'cert fingerprint'
```

### 🛠️ Enabling Multiple Plugins

To enable multiple plugins, update the `command` section in `docker-compose.yml`. For example, to enable both the
`monitor` and `outline` plugins:

```yaml
command: --plugins monitor,outline
```

Then run:

```bash
docker-compose up -d
```

## 📋 Plugin Details

### 📊 Monitor Plugin

#### Overview

The Monitor Plugin provides real-time monitoring of CPU, memory, temperature _(only on Linux)_ and disk usage on the
server where pyTMbot is running.
It sends notifications to the administrator if any of the thresholds defined in `pytmbot.yaml` are exceeded.

#### Configuration

Monitor Plugin settings are defined in `pytmbot.yaml` under `plugins_config.monitor`. This includes thresholds for
resource usage, notification limits, and retry attempts.

#### Usage

Once enabled, the Monitor Plugin automatically tracks system resource usage based on the settings provided. It will
notify administrators if thresholds are exceeded.

#### Customization

All thresholds and monitoring behavior can be customized via the `pytmbot.yaml` configuration file. Users can set their
own CPU, memory, and disk usage limits, as well as adjust retry logic and notification intervals.

### 🛡️ Outline Plugin

#### Overview

The Outline Plugin integrates with the Outline VPN server API to manage access keys, retrieve server statistics, update
server settings, and monitor data usage.

#### Configuration

The Outline Plugin is configured in `pytmbot.yaml` under the `plugins_config.outline` section. The API URL and
certificate path
are specified here.

#### Usage

After enabling the plugin, it provides an interface for interacting with the Outline VPN server, allowing key management
and server configuration updates based on the provided credentials.

## 🚀 Future Enhancements

- Additional plugins and features may be added in future updates.
- Continued improvements to plugin stability and functionality.