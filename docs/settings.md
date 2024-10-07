Here’s a Markdown documentation detailing the configurations necessary for each command-line argument in your PyTMBot. This includes explanations of how to set up each argument effectively:

# ⚙️ PyTMBot Configuration Settings

When using PyTMBot, you can customize its behavior through various command-line arguments. Below, you'll find a comprehensive guide on the required configurations associated with each argument.

## 🌐 General Bot Settings

### Bot Token Configuration
- **`--mode`**: 
  - **Production (`prod`)**: 
    - Set `prod_token` to your actual production bot token.
  - **Development (`dev`)**: 
    - Optionally set `dev_bot_token` if you wish to run the bot in development mode.

```yaml
bot_token:
  prod_token:
    - 'YOUR_PROD_BOT_TOKEN'  # Replace with your actual production bot token.
  dev_bot_token:
    - 'YOUR_DEV_BOT_TOKEN'    # Replace with your development bot token (if needed).
```
Chat ID Configuration

```yaml
chat_id:
	•	Set global_chat_id to the chat ID where notifications will be sent.

chat_id:
  global_chat_id:
    - 'YOUR_CHAT_ID'  # Replace with your actual chat ID for notifications.

Access Control Settings

	•	access_control:
	•	Define allowed_user_ids and allowed_admins_ids to restrict access.
	•	Set auth_salt for generating TOTP secrets.

access_control:
  allowed_user_ids: [USER_ID_1, USER_ID_2]  # Replace with allowed user IDs.
  allowed_admins_ids: [ADMIN_ID_1, ADMIN_ID_2]  # Replace with allowed admin IDs.
  auth_salt:
    - 'YOUR_AUTH_SALT'  # Replace with the salt for TOTP.

🐳 Docker Settings

	•	Docker Socket Configuration:
	•	Ensure that the Docker socket is correctly specified. Typically, it’s set to unix:///var/run/docker.sock.

docker:
  host:
    - 'unix:///var/run/docker.sock'  # Path to the Docker socket.

🌐 Webhook Configuration

	•	--webhook:
	•	If set to True, configure the webhook settings:
	•	Replace url with your actual webhook URL.
	•	Specify webhook_port for external requests (default is 443).
	•	Define local_port for internal requests.
	•	Provide paths to your SSL certificate and key if using HTTPS.

webhook_config:
  url:
    - 'YOUR_WEBHOOK_URL'  # Replace with your actual webhook URL.
  webhook_port:
    - 443  # Port for external webhook requests.
  local_port:
    - 5001  # Local port for internal requests.
  cert:
    - 'YOUR_CERTIFICATE'  # Path to the SSL certificate (if using HTTPS).
  cert_key:
    - 'YOUR_CERTIFICATE_KEY'  # Path to the SSL certificate's private key (if using HTTPS).

🧩 Plugins Configuration

Monitor Plugin

	•	Monitoring Settings:
	•	Configure threshold values for CPU, memory, disk, and temperature.
	•	Adjust max_notifications, check_interval, and reset_notification_count as needed.

plugins_config:
  monitor:
    tracehold:
      cpu_usage_threshold:
        - 80  # Adjust CPU usage threshold.
      memory_usage_threshold:
        - 80  # Adjust memory usage threshold.
      disk_usage_threshold:
        - 80  # Adjust disk usage threshold.
      cpu_temperature_threshold:
        - 85  # Adjust CPU temperature threshold.
      gpu_temperature_threshold:
        - 90  # Adjust GPU temperature threshold.
      disk_temperature_threshold:
        - 60  # Adjust disk temperature threshold.
    max_notifications:
      - 3  # Set the maximum number of notifications.
    check_interval:
      - 5  # Set the interval for system checks.
    reset_notification_count:
      - 5  # Reset count after X minutes.
    retry_attempts:
      - 3  # Set number of retry attempts.
    retry_interval:
      - 10  # Set interval between retry attempts.
    monitor_docker: True  # Set to True to monitor Docker images and containers.

Outline Plugin

	•	Outline API Settings:
	•	Replace api_url and cert with your actual Outline API URL and certificate path.

outline:
  api_url:
    - 'YOUR_OUTLINE_API_URL'  # Replace with your actual Outline API URL.
  cert:
    - 'YOUR_OUTLINE_CERT'  # Replace with the actual path to your certificate.

📊 InfluxDB Settings

	•	InfluxDB Configuration:
	•	Set the url, token, org, and bucket to connect to your InfluxDB instance.
	•	Optionally, enable debug_mode for debugging purposes.

influxdb:
  url:
    - 'YOUR_INFLUXDB_URL'  # URL of your InfluxDB server.
  token:
    - 'YOUR_INFLUXDB_TOKEN'  # Replace with your actual InfluxDB token.
  org:
    - 'YOUR_INFLUXDB_ORG'  # Replace with your actual organization name.
  bucket:
    - 'YOUR_INFLUXDB_BUCKET'  # Replace with your actual bucket name.
  debug_mode: YOUR_INFLUXDB_DEBUG_MODE  # Set to true to enable debug mode.

📜 Conclusion

Make sure to replace placeholder values with your actual configurations to ensure proper functionality. If you have any questions or need assistance, refer to the PyTMBot documentation or reach out for support.

Happy Botting! 🤖

Feel free to modify any sections as needed, and let me know if you need any additional changes or information!