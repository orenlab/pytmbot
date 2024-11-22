# 🎛️ PyTMBot Command-Line Arguments

The PyTMBot supports several command-line arguments to customize its behavior. Below is a detailed description of each
argument you can use when starting the bot.

## 🛠️ Arguments

| Argument        | Type   | Default     | Choices                  | Description                                                                                     |
|-----------------|--------|-------------|--------------------------|-------------------------------------------------------------------------------------------------|
| `--mode`        | `str`  | `prod`      | `dev`, `prod`            | Select the mode of operation for PyTMBot. Use `dev` for development and `prod` for production.  |
| `--log-level`   | `str`  | `INFO`      | `DEBUG`, `INFO`, `ERROR` | Set the logging level for the bot. More verbose logs can be helpful during development.         |
| `--webhook`     | `str`  | `False`     | `True`, `False`          | Start the bot in webhook mode. Useful for receiving updates via HTTP callbacks.                 |
| `--socket_host` | `str`  | `127.0.0.1` | N/A                      | Define the host address for the socket to listen on in webhook mode. Default is localhost.      |
| `--plugins`     | `list` | `[]`        | N/A                      | Specify a list of plugins to load when starting the bot. Separate multiple plugins with spaces. |
| `--salt`        | `str`  | `False`     | N/A                      | Generate unique salt for using it in TOTP auth                                                  |

## 📄 Required Configurations

Depending on the command-line arguments you choose, certain configuration settings must be filled out in your
configuration file. Below are the sections you need to complete:

### General Bot Settings

- **Bot Token Configuration**: Ensure you provide the correct `prod_token` or `dev_bot_token`.
- **Chat ID Configuration**: Set your `global_chat_id` for notifications.
- **Access Control Settings**: Specify `allowed_user_ids`, `allowed_admins_ids`, and `auth_salt`.

### Webhook Configuration (if using `--webhook True`)

- **webhook_config**: Fill the parameters in the `webhook_config` section.

Bot cannot be run in 80 port for security reasons. Use reverse proxy to run the bot (e.g. Nginx, Nginx Proxy Manager or
Traefik).

### Plugins Configuration (if using `--plugins`)

- **Monitor Plugin**: Adjust the threshold values in the `monitor` section of your configuration.
  `InfluxDB` is required for `Monitor Plugin`. **InfluxDB Settings**: Set the `url`, `token`, `org`, and `bucket`
  values.
- **Outline Plugin**: Set the `api_url` and `cert` paths for the Outline API.

## 🚀 Usage Example

To start the PyTMBot in development mode with debug logging and the monitor plugin enabled, you can run the following
command:

```bash
python main.py --mode dev --log-level DEBUG --plugins monitor
```

To run the bot in production mode with webhook support, use:

```bash
python main.py --mode prod --webhook True
```

📜 Notes

- Ensure that the arguments are provided in the correct format and within the allowed choices.
- For any questions or further assistance, feel free to check out the PyTMBot documentation or open an issue in the
  repository.

Happy Botting! 🤖