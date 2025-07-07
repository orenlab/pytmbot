# Running pyTMBot in DEBUG Mode

To run pyTMBot in DEBUG mode, follow these steps:

## 1. **Stop the Running Container**

If the pyTMBot container is currently running, you need to stop it first:

```bash
sudo docker stop pytmbot
```

## 2. **Remove the Stopped Container**

Once the container is stopped, remove it:

```bash
sudo docker rm pytmbot
```

## 3. **Run pyTMBot in DEBUG Mode**

Launch the pyTMBot container in DEBUG mode by executing the following command:

```bash
sudo docker run -d \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
  --env TZ="Asia/Yekaterinburg" \
  --restart=always \
  --name=pytmbot \
  --pid=host \
  --security-opt=no-new-privileges \
  orenlab/pytmbot:latest \
  --log-level DEBUG --mode prod
```

### Command Line Arguments Explanation:

- `--log-level DEBUG`: Sets the logging level to DEBUG, providing detailed information for troubleshooting
- `--mode prod`: Specifies the production mode for the bot

### Available Options:

- **Log Levels**: `DEBUG`, `INFO`, `ERROR`
- **Modes**: `dev`, `prod`
- **Additional Options**:
    - `--plugins monitor,outline`: Load specific plugins
    - `--webhook True`: Enable webhook mode
    - `--socket_host 0.0.0.0`: Set host for webhook mode

## 4. **Access the Bot's Logs**

To view the logs for the pyTMBot container, use the following command:

```bash
sudo docker logs pytmbot
```

For real-time log monitoring:

```bash
sudo docker logs -f pytmbot
```

This will display the log output for the bot, including detailed DEBUG information.

## 5. **Development Mode Alternative**

For development purposes, you can also run the bot in development mode with debug logging:

```bash
sudo docker run -d \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
  --env TZ="Asia/Yekaterinburg" \
  --restart=always \
  --name=pytmbot \
  --pid=host \
  --security-opt=no-new-privileges \
  orenlab/pytmbot:latest \
  --log-level DEBUG --mode dev
```

## 6. **Health Check and Diagnostics**

Before running in DEBUG mode, you can perform health checks:

```bash
# Health check
sudo docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
  orenlab/pytmbot:latest \
  --health_check

# Docker configuration check
sudo docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  orenlab/pytmbot:latest \
  --check-docker
```

## 🛡️ Security Note

**Important**: DEBUG mode may contain sensitive information in logs. Use it only for troubleshooting and never in
production environments where logs might be exposed.

## 🔧 Troubleshooting

If you encounter issues:

1. Check Docker permissions: `sudo docker run --rm orenlab/pytmbot:latest --check-docker`
2. Verify configuration:
   `sudo docker run --rm -v /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro orenlab/pytmbot:latest --health_check`
3. Review logs: `sudo docker logs pytmbot`

For additional help, refer to the full CLI arguments documentation.