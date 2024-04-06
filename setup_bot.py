#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

try:
    import click
except ImportError:
    raise ImportError("Error loading 'click' package. Install it!")
from string import Template

import bot_cli.cfg_templates.bot_settings as default_bot_tpl
import bot_cli.cfg_templates.env as default_env_tpl

from bot_cli import fs as filesystem

APP_CONFIG_FILE = 'app/core/settings/bot_settings.py'
APP_ENV_FILE = '.env'


def ask_for_user_id() -> str:
    click.secho("[-] Let's added allowed user ID`s:", bg='blue', fg='white', bold=False)
    click.echo("""
        Format (one user ID): 123456789\n
        Format (more than one user ID): 123456789, 123654987\n
        """)

    return click.prompt("User IDS", default="00000000000, 00000000000")


def ask_for_docker_host() -> str:
    click.secho("[-] Let's added Docker host:", bg='blue', fg='white', bold=False)
    click.echo("""
        Format: unix:///var/run/docker.sock\n
        """)

    return click.prompt("Glances host", default="unix:///var/run/docker.sock")


def ask_for_dev_token() -> str:
    click.secho("[-] Let's added Development bot token:", bg='blue', fg='white', bold=False)
    click.echo("""
        Format: 1234567890:FFGGEWGLKxOSLNwoLY7ADlFTt3TjtlrEcYl7hg\n
        """)

    return click.prompt("Dev bot token", default="")


def ask_for_prod_token() -> str:
    click.secho("[-] Let's added Production bot token:", bg='blue', fg='white', bold=False)
    click.echo("""
        Format: 1234567890:FFGGEWGLKxOSLNwoLY7ADlFTt3TjtlrEcYl7hg\n
        """)

    return click.prompt("Production bot token", default="")


def create_default_config() -> None:
    user_id = ask_for_user_id()
    docker_host = ask_for_docker_host()

    variables: dict = {
        "user_id": user_id,
        "docker_host": docker_host
    }

    filesystem.set_file(
        APP_CONFIG_FILE,
        Template(default_bot_tpl.DEFAULT_BOT_SETTINGS).substitute(variables)
    )

    click.echo(click.style("[+] %s created." % APP_CONFIG_FILE, fg="green", bold=True))


def create_dot_env() -> None:
    dev_token = ask_for_dev_token()
    prod_token = ask_for_prod_token()

    variables: dict = {
        "dev_token": dev_token,
        "prod_token": prod_token,
    }

    filesystem.set_file(
        APP_ENV_FILE,
        Template(default_env_tpl.ENV_TEMPLATE).substitute(variables)
    )

    click.secho("[+] %s created." % APP_ENV_FILE, fg="green", bold=True)


@click.command()
def build_config() -> None:
    click.secho("*** Starting build default app configuration ***", fg="green", bold=True)

    # app/core/settings/bot_settings.py
    if filesystem.has_file(APP_CONFIG_FILE):
        click.secho("Looks like you already have %s, if you need reconfigure bot, remove it." % APP_CONFIG_FILE,
                    blink=True, fg="yellow", bold=True)
    else:
        create_default_config()

    click.secho("*** Starting build default .env ***", fg="green", bold=True)

    # .env
    if filesystem.has_file(APP_ENV_FILE):
        click.secho("Looks like you already have .env, if you need reconfigure bot, remove it.", blink=True,
                    fg="yellow", bold=True)
    else:
        create_dot_env()

    click.secho("All done. Now you can build Docker image and run bot.", blink=True, bg='blue', fg='white', bold=True)


if __name__ == '__main__':
    build_config()
