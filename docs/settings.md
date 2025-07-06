# 🤖 PyTMBot Configuration Guide

Complete guide for configuring PyTMBot with detailed explanations and configuration examples.

## 🚀 Quick Start

### Minimum requirements to run:

1. Bot token from @BotFather
2. Your Telegram User ID
3. Chat ID for notifications
4. Secret key for TOTP authentication

### Getting required data:

#### 1. Getting bot token:

- Message @BotFather on Telegram
- Create a new bot with `/newbot` command
- Copy the token (format: `1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk`)

#### 2. Getting your User ID:

- **Method 1**: Send a message to @userinfobot
- **Method 2**: Start your bot and send any message, check logs for user ID

#### 3. Getting Chat ID:

- **For private messages**: use your User ID (positive number)
- **For groups**: add @userinfobot to the group and send a message (negative number)
- **Through logs**: start your bot and send a message, check logs for chat ID

#### 4. Generating secret key:

```bash
# Using Docker
docker run --rm orenlab/pytmbot:latest --salt

# Using OpenSSL
openssl rand -hex 32

# Or any random string of 32+ characters
```

## ⚙️ Complete Configuration

### 🔧 General Bot Settings

#### Bot Token Configuration

```yaml
bot_token:
  # Production bot token (REQUIRED)
  prod_token:
    - 'YOUR_PROD_BOT_TOKEN'  # Example: '1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk'

  # Development bot token (OPTIONAL)
  # Use separate bot for testing to avoid conflicts
  dev_bot_token:
    - 'YOUR_DEV_BOT_TOKEN'   # Example: '9876543210:ZYXWVUTSRQPONMLKJIHGFEDCBAzyxwvutsrqp'
```

#### Access Control Settings

```yaml
access_control:
  # User IDs allowed to access the bot (REQUIRED)
  allowed_user_ids:
    - 123456789    # Replace with actual Telegram user ID
    - 987654321    # You can add multiple user IDs

  # Admin IDs with elevated permissions (REQUIRED)
  allowed_admins_ids:
    - 123456789    # Replace with actual admin Telegram user ID

  # Salt for TOTP generation (REQUIRED)
  # Generate with: docker run --rm orenlab/pytmbot:latest --salt
  auth_salt:
    - 'your-secret-random-32-char-salt-here-replace-this-value'
```

#### Chat ID Configuration

```yaml
chat_id:
  # Global chat ID for notifications (REQUIRED)
  global_chat_id:
    - -1001234567890  # Example: group chat ID (negative number)
    # - 123456789     # Alternative: private chat ID (positive number)
```

### 🐳 Docker Settings

```yaml
docker:
  # Docker socket path (REQUIRED)
  # Default for Linux: unix:///var/run/docker.sock
  # For Windows: npipe:////./pipe/docker_engine
  host:
    - 'unix:///var/run/docker.sock'

  # Enable Docker client debug logging (OPTIONAL)
  # WARNING: Produces many logs when monitor plugin is enabled
  debug_docker_client: false  # true or false
```

### 🌐 Webhook Configuration (Advanced)

**Note**: Bot automatically generates random webhook paths and secret tokens for enhanced security.

```yaml
webhook_config:
  # Webhook URL (REQUIRED if using webhooks)
  # Must be accessible from the internet with valid SSL
  # Bot automatically appends secure random path
  url:
    - 'your-domain.com'  # Replace with your domain (without https:// and path)

  # External webhook port (REQUIRED if using webhooks)
  webhook_port:
    - 8443  # Standard HTTPS port (recommended)
    # - 443   # Alternative port (allowed by Telegram)

  # Local application port (REQUIRED if using webhooks)
  local_port:
    - 5001  # Internal port for the bot application (must be >= 1024)

  # SSL certificate path (OPTIONAL for HTTPS webhooks)
  cert:
    - '/path/to/your/certificate.pem'

  # SSL private key path (OPTIONAL for HTTPS webhooks)
  cert_key:
    - '/path/to/your/private.key'
```

### 🔌 Plugins Configuration

#### System Monitoring Plugin

```yaml
plugins_config:
  monitor:
    # Resource usage thresholds
    tracehold:
      cpu_usage_threshold:
        - 80  # Alert when CPU usage exceeds 80%
      memory_usage_threshold:
        - 80  # Alert when memory usage exceeds 80%
      disk_usage_threshold:
        - 80  # Alert when disk usage exceeds 80%
      cpu_temperature_threshold:
        - 85  # Alert when CPU temperature exceeds 85°C
      gpu_temperature_threshold:
        - 90  # Alert when GPU temperature exceeds 90°C
      disk_temperature_threshold:
        - 60  # Alert when disk temperature exceeds 60°C

    # Notification settings
    max_notifications:
      - 3  # Stop sending alerts after 3 notifications for same issue
    check_interval:
      - 5  # Check system status every 5 seconds
    reset_notification_count:
      - 5  # Reset notification counter after 5 minutes

    # Retry settings
    retry_attempts:
      - 3  # Try 3 times before giving up
    retry_interval:
      - 10  # Wait 10 seconds between retries

    # Docker monitoring
    monitor_docker: true  # Monitor Docker containers and images
```

#### Outline VPN Plugin

```yaml
outline:
  # Outline VPN API URL (REQUIRED if using Outline plugin)
  api_url:
    - 'https://your-outline-server.com:12345/api'

  # Certificate fingerprint (REQUIRED if using Outline plugin)
  cert:
    - 'YOUR_OUTLINE_CERT_FINGERPRINT'
```

### 📊 InfluxDB Integration (Optional)

```yaml
influxdb:
  # InfluxDB server URL
  url:
    - 'http://localhost:8086'

  # InfluxDB access token
  # Generate in InfluxDB web interface: Data > Tokens > Generate Token
  token:
    - 'YOUR_INFLUXDB_TOKEN'

  # InfluxDB organization name
  org:
    - 'YOUR_INFLUXDB_ORG'

  # InfluxDB bucket name
  bucket:
    - 'YOUR_INFLUXDB_BUCKET'

  # Debug mode
  debug_mode: false  # Enable debug logs
```

## 🐳 Docker Usage

### Basic Docker Commands

#### Run with polling (default):

```bash
docker run -d \
  --name pytmbot \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/config.yaml:/app/config.yaml \
  orenlab/pytmbot:latest
```

#### Run with webhooks:

```bash
docker run -d \
  --name pytmbot \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/config.yaml:/app/config.yaml \
  -p 8443:8443 \
  orenlab/pytmbot:latest --webhook
```

#### Run with specific plugins:

```bash
docker run -d \
  --name pytmbot \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/config.yaml:/app/config.yaml \
  orenlab/pytmbot:latest --plugins monitor,outline
```

### Command Line Options

| Option           | Description                        | Default   |
|------------------|------------------------------------|-----------|
| `--log-level`    | Set log level (DEBUG, INFO, ERROR) | INFO      |
| `--mode`         | Set mode (dev, prod)               | prod      |
| `--salt`         | Generate salt for TOTP             | False     |
| `--plugins`      | Comma-separated list of plugins    | ""        |
| `--webhook`      | Enable webhook mode                | False     |
| `--socket_host`  | Socket host for webhook            | 127.0.0.1 |
| `--health_check` | Perform health check               | False     |
| `--check-docker` | Check Docker access and exit       | -         |

### Examples

#### Generate salt:

```bash
docker run --rm orenlab/pytmbot:latest --salt
```

#### Check Docker access:

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  orenlab/pytmbot:latest --check-docker
```

#### Run in development mode:

```bash
docker run -d \
  --name pytmbot-dev \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/config.yaml:/app/config.yaml \
  orenlab/pytmbot:latest --mode dev --log-level DEBUG
```

## 🔒 Security Features

### Automatic Security Enhancements:

- **Random webhook paths**: Bot generates secure random paths for webhooks
- **Rate limiting**: 10 requests per 10 seconds, 5 for 404 errors
- **IP validation**: Only Telegram servers are allowed
- **Secret token verification**: Webhook requests are verified
- **Automatic IP banning**: After 50 excessive requests
- **Docker group management**: Automatic Docker socket access configuration

### Manual Security Recommendations:

- Use separate bot tokens for development and production
- Restrict `allowed_user_ids` to trusted users only
- Use strong, unique `auth_salt` values
- Enable HTTPS for webhook configurations
- Regularly rotate bot tokens and secrets
- Monitor logs for suspicious activity

## 🩺 Health Checks & Monitoring

### Health Check Command:

```bash
docker run --rm \
  -v /path/to/config.yaml:/app/config.yaml \
  orenlab/pytmbot:latest --health_check
```

### Docker Health Check:

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python3 pytmbot/main.py --health_check
```

### Monitoring Logs:

```bash
# View logs
docker logs pytmbot

# Follow logs
docker logs -f pytmbot

# View logs with timestamps
docker logs -t pytmbot
```

## 🛠️ Troubleshooting

### Common Issues:

#### 1. Docker socket permission denied:

```bash
# Check Docker socket permissions
ls -la /var/run/docker.sock

# Fix with Docker group
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  orenlab/pytmbot:latest --check-docker

# Or use group-add
docker run --group-add $(stat -c %g /var/run/docker.sock) ...
```

#### 2. Bot not responding:

- Check bot token validity
- Verify user IDs in `allowed_user_ids`
- Check network connectivity
- Review logs for errors

#### 3. Webhook issues:

- Ensure domain is accessible from internet
- Verify SSL certificate validity
- Check firewall settings
- Confirm webhook URL format

#### 4. Configuration errors:

- Validate YAML syntax
- Check file permissions
- Verify all required fields are filled
- Test with minimal configuration first

### Debug Mode:

```bash
docker run -d \
  --name pytmbot-debug \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/config.yaml:/app/config.yaml \
  orenlab/pytmbot:latest --log-level DEBUG
```

## 📋 Configuration Templates

### Minimal Configuration:

```yaml
bot_token:
  prod_token:
    - 'YOUR_BOT_TOKEN'

access_control:
  allowed_user_ids:
    - YOUR_USER_ID
  allowed_admins_ids:
    - YOUR_USER_ID
  auth_salt:
    - 'YOUR_GENERATED_SALT'

chat_id:
  global_chat_id:
    - YOUR_CHAT_ID

docker:
  host:
    - 'unix:///var/run/docker.sock'
```

## 🎯 Best Practices

1. **Start Simple**: Begin with minimal configuration and add features gradually
2. **Test Thoroughly**: Test each configuration change in development mode
3. **Monitor Logs**: Regularly check logs for errors and security issues
4. **Backup Configuration**: Keep backups of working configurations
5. **Update Regularly**: Keep PyTMBot updated to latest version
6. **Security First**: Follow security recommendations and best practices
7. **Document Changes**: Keep track of configuration changes and their purposes

## 📞 Support

- **Documentation**: Check the PyTMBot documentation for detailed information
- **Issues**: Report bugs and feature requests on the project repository
- **Community**: Join the community discussions for help and tips
- **Logs**: Always include relevant logs when seeking help

Happy Botting! 🤖✨