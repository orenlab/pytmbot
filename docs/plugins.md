pyTMbot Plugins 🌟

pyTMbot supports a plugin system that allows you to extend the bot’s functionality. This document describes the
supported plugins and their configuration.

🧩 Supported Plugins

- Monitor: Provides real-time monitoring of server resources such as CPU, memory, temperature (Linux only), and disk
  usage. It also monitors Docker containers and images, sending notifications about potential security incidents when
  new ones are detected.
- Outline: Integrates with the Outline VPN server API, allowing you to manage access keys and update server settings.

⚙️ Plugin Usage

Plugins do not require separate installation. To activate the desired plugins, use the --plugins argument when starting
the container.

🐳 Example Usage with Docker Compose

Create a docker-compose.yml file with the following configuration:

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
    security_opt:
      - no-new-privileges
    read_only: true  # Make the container's filesystem read-only to reduce risks
    cap_drop:
      - ALL  # Drop all capabilities to minimize attack surfaces
    pid: host  # Use the host's PID namespace for monitoring processes (use with caution)
    logging:
      options:
        max-size: "10m"
        max-file: "3"
    command: --plugins monitor,outline --log-level DEBUG  # Bot start parameters: logging and plugins`
```

To start the container:

```bash
docker-compose up -d
```

📋 Plugin Details

📊 Monitor Plugin

Overview

The Monitor plugin provides real-time monitoring of server resources such as CPU, memory, temperature (Linux only), and
disk usage. It also monitors Docker containers and images, sending notifications about potential security incidents when
new ones are detected.

Configuration

Monitor plugin settings are located in the pytmbot.yaml file under plugins_config.monitor. Here’s an example
configuration:

```yaml
plugins_config:
  monitor:
    # Threshold settings
    tracehold:
      cpu_usage_threshold: [ 80 ]  # CPU usage threshold in percentage
      memory_usage_threshold: [ 80 ]  # Memory usage threshold in percentage
      disk_usage_threshold: [ 80 ]  # Disk usage threshold in percentage
      cpu_temperature_threshold: [ 85 ]  # CPU temperature threshold in Celsius
      gpu_temperature_threshold: [ 90 ]  # GPU temperature threshold in Celsius
      disk_temperature_threshold: [ 60 ]  # Disk temperature threshold in Celsius
    # Notification settings
    max_notifications: [ 3 ]  # Maximum number of notifications for each type of overload
    check_interval: [ 7 ]  # Check interval in seconds
    reset_notification_count: [ 5 ]  # Reset notification count after X minutes
    retry_attempts: [ 3 ]  # Number of attempts to restart monitoring in case of failure
    retry_interval: [ 10 ]  # Interval (in seconds) between retry attempts
    monitor_docker: True  # Enable monitoring of Docker containers and images
```

You also need to configure InfluxDB settings:

```yaml
influxdb:
  url: [ 'YOUR_INFLUXDB_URL' ]
  token: [ 'YOUR_INFLUXDB_TOKEN' ]
  org: [ 'YOUR_INFLUXDB_ORG' ]
  bucket: [ 'YOUR_INFLUXDB_BUCKET' ]
  debug_mode: false
```

Behavior

Once enabled, the Monitor plugin tracks server resources as well as Docker containers and images. It sends notifications
to administrators when resource thresholds are exceeded or when new containers and images are detected.

🛡️ Outline Plugin

Overview

The Outline plugin integrates with the Outline VPN server API, allowing you to manage access keys, retrieve server
statistics, update server settings, and monitor data usage.

Configuration

The Outline plugin is configured in the plugins_config.outline section of the pytmbot.yaml file. Example configuration:

```yaml
plugins_config:
  outline:
    api_url: [ 'https://your-outline-server.com' ]
    cert: [ 'cert fingerprint' ]
```

Behavior

Once enabled, the Outline plugin provides an interface to interact with the Outline VPN server, allowing key management
and server configuration updates based on the provided credentials.

🛠️ Enabling Multiple Plugins

To activate multiple plugins, update the command section in the docker-compose.yml file. For example, to enable both the
Monitor and Outline plugins:

```yaml
command: --plugins monitor,outline
```

Then run:

```bash
docker-compose up -d
```

🚀 Future Enhancements

- Additional plugins and features may be added in future updates.
- Continued improvements to plugin stability and functionality.