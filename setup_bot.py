#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import click
import jinja2

from cli.generate_salt import generate_random_auth_salt

import warnings

warnings.warn(
    "This module is deprecated and will be removed in a 0.2.0 release version. "
    "Please use 'install.sh' instead (https://github.com/orenlab/pytmbot/blob/master/install.sh)",
    DeprecationWarning,
    stacklevel=1
)

APP_ENV_FILE = Path("pytmbot.yaml")

config_template = """
# Setup bot tokens
bot_token:
  # Prod bot token.
  prod_token:
    - '{{ prod_token }}'
  # Development bot token. Not necessary for production bot.
  dev_bot_token:
    - '{{ dev_token }}'

# Setup access control
access_control:
  # The ID of the users who have permission to access the bot.
  # You can have one or more values - there are no restrictions.
  allowed_user_ids:
    {% for user_id in user_id %}
    - '{{ user_id }}'
    {% endfor %}
  # The ID of the admins who have permission to access the bot.
  # You can have one or more values, there are no restrictions.
  # However, it's important to keep in mind that these users will be able to manage Docker images and containers.
  allowed_admins_ids:
    {% for admin_id in admin_id %}
    - '{{ admin_id }}'
    {% endfor %}
  # Salt is used to generate TOTP (Time-Based One-Time Password) secrets and to verify the TOTP code.
  # A script for the fast generation of a truly unique "salt" is available in the bot's repository.
  auth_salt:
    - '{{ auth_salt }}'

# Docker settings
docker:
  # Docker socket. Usually: unix:///var/run/docker.sock.
  host:
    - '{{ docker_host }}'

{% if plugins_enabled %}
# Plugins configuration
plugins_config:
  # Configuration for Monitor plugin
  monitor:
    # Tracehold settings
    tracehold:
      # CPU usage thresholds in percentage
      cpu_usage_threshold:
        - {{ monitor_config.cpu_usage_threshold[0] }}
      # Memory usage thresholds in percentage
      memory_usage_threshold:
        - {{ monitor_config.memory_usage_threshold[0] }}
      # Disk usage thresholds in percentage
      disk_usage_threshold:
        - {{ monitor_config.disk_usage_threshold[0] }}
      # Number of notifications to send for each type of overload
    max_notifications:
      - {{ monitor_config.max_notifications[0] }}
    # Check interval in seconds
    check_interval:
      - {{ monitor_config.check_interval[0] }}
    # Reset notification count after X minutes
    reset_notification_count:
      - {{ monitor_config.reset_notification_count[0] }}
    # Number of attempts to retry starting monitoring in case of failure
    retry_attempts:
      - {{ monitor_config.retry_attempts[0] }}
    # Interval (in seconds) between retry attempts
    retry_interval:
      - {{ monitor_config.retry_interval[0] }}

  # Configuration for Outline plugin
  outline:
    # Outline API settings
    api_url:
      - '{{ outline_config.api_url[0] }}'
    cert:
      - '{{ outline_config.cert[0] }}'
{% endif %}
"""

TOKEN_REGEX = re.compile(r"^[a-zA-Z0-9-]+$")
ID_REGEX = re.compile(r"^\d+$")


def set_file(file_path: Path, file_content: str) -> None:
    """Writes the given content to a file."""
    with open(file_path, "w") as f:
        f.write(file_content)


def validate_token(token: str) -> None:
    """Validates that the token contains only alphanumeric characters and hyphens."""
    if not TOKEN_REGEX.match(token):
        raise ValueError(
            f"Invalid token: {token}. Tokens must contain only letters, numbers, and hyphens."
        )


def validate_ids(ids: str) -> None:
    """Validates that the IDs contain only digits."""
    for _id in ids.split(","):
        if not ID_REGEX.match(_id.strip()):
            raise ValueError(f"Invalid ID: {id}. IDs must contain only digits.")


@dataclass
class BotConfig:
    dev_token: Optional[str]
    prod_token: str
    user_id: str
    admin_id: str
    docker_host: str
    auth_salt: str
    plugins_enabled: Optional[bool] = None
    plugins_config: Optional[Dict[str, dict]] = None


def prompt_for_input(
        prompt_text: str,
        default: Optional[str] = "",
        mandatory: bool = False,
        validation_func: Optional[callable] = None,
) -> str:
    """Prompts the user for input and applies validation."""
    if mandatory:
        while True:
            click.echo(f"{prompt_text} (required):")
            value = click.prompt(prompt_text, default=default, show_default=False)
            if value:
                if validation_func:
                    try:
                        validation_func(value)
                    except ValueError as e:
                        click.secho(str(e), fg="red", bold=True)
                        continue
                return value
            else:
                click.secho(
                    "This field is required. Please try again.", fg="red", bold=True
                )
    else:
        click.echo(prompt_text)
        value = click.prompt(prompt_text, default=default)
        if validation_func:
            try:
                validation_func(value)
            except ValueError as e:
                click.secho(str(e), fg="red", bold=True)
        return value


def prompt_for_yes_no(prompt_text: str) -> bool:
    """Prompts the user with a yes/no question."""
    click.echo(prompt_text)
    return click.confirm(prompt_text, default=False)


def create_config() -> BotConfig:
    """Creates a configuration object based on user input."""
    click.secho("*** Starting pytmbot.yaml configuration ***", fg="green", bold=True)

    prod_token = prompt_for_input(
        "Production bot token:", mandatory=True, validation_func=validate_token
    )
    dev_token = prompt_for_input(
        "Development bot token (optional):", default="", validation_func=validate_token
    )
    user_id = prompt_for_input(
        "User IDs (comma-separated):", mandatory=True, validation_func=validate_ids
    )
    admin_id = prompt_for_input(
        "Admin User IDs (comma-separated):",
        mandatory=True,
        validation_func=validate_ids,
    )
    docker_host = prompt_for_input("Docker host:", "unix:///var/run/docker.sock")
    auth_salt = prompt_for_input(
        "Auth salt (leave empty for a random value):",
        default=generate_random_auth_salt(),
    )

    plugins_enabled = prompt_for_yes_no("Enable plugin support?")

    plugins_config = None
    if plugins_enabled:
        plugins_config = {
            "monitor": {
                "cpu_usage_threshold": [80],
                "memory_usage_threshold": [80],
                "disk_usage_threshold": [80],
                "max_notifications": [3],
                "check_interval": [2],
                "reset_notification_count": [5],
                "retry_attempts": [3],
                "retry_interval": [10],
            },
            "outline": {"api_url": [""], "cert": [""]},
        }

    return BotConfig(
        dev_token=dev_token,
        prod_token=prod_token,
        user_id=user_id,
        admin_id=admin_id,
        docker_host=docker_host,
        auth_salt=auth_salt,
        plugins_enabled=plugins_enabled,
        plugins_config=plugins_config,
    )


def render_template(template_content: str, variables: Dict[str, any]) -> str:
    """Renders the configuration template with the given variables."""
    template = jinja2.Template(template_content)
    return template.render(variables)


def save_config_to_file(config: BotConfig) -> None:
    """Saves the configuration to a YAML file."""
    variables = {
        "dev_token": config.dev_token or "",
        "prod_token": config.prod_token,
        "user_id": config.user_id.split(","),
        "admin_id": config.admin_id.split(","),
        "docker_host": config.docker_host,
        "auth_salt": config.auth_salt,
        "plugins_enabled": "true" if config.plugins_enabled else "false",
        "monitor_config": (
            config.plugins_config["monitor"] if config.plugins_enabled else {}
        ),
        "outline_config": (
            config.plugins_config["outline"] if config.plugins_enabled else {}
        ),
    }

    template_content = render_template(config_template, variables)
    set_file(APP_ENV_FILE, template_content)
    click.secho(
        f"[+] Configuration file {APP_ENV_FILE} created.", fg="green", bold=True
    )


@click.command()
def build_config() -> None:
    """Builds the configuration file."""
    if APP_ENV_FILE.exists():
        click.secho(
            f"{APP_ENV_FILE} already exists. Please delete it to recreate.",
            fg="yellow",
            bold=True,
        )
    else:
        config = create_config()
        save_config_to_file(config)

    click.secho(
        "Configuration complete. You can now build the Docker image and run the bot.",
        fg="white",
        bg="blue",
        bold=True,
    )


if __name__ == "__main__":
    build_config()
