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

import bot_cli.cfg_templates.env as default_env_tpl

from bot_cli import fs as filesystem

APP_ENV_FILE = '.pytmbotenv'


def ask_for_user_id() -> str:
    click.secho("[-] Let's added allowed user ID`s:", bg='blue', fg='white', bold=False)
    click.echo("""
        Format (one user ID): 000000000000\n
        Format (more than one user ID): 000000000000, 000000000000, 000000000000\n
        """)

    return click.prompt("User IDS")


def ask_for_docker_host() -> str:
    click.secho("[-] Let's added Docker host:", bg='blue', fg='white', bold=False)
    click.echo("""
        Format: unix:///var/run/docker.sock\n
        """)

    return click.prompt("Docker host", default="unix:///var/run/docker.sock")


def ask_for_podman_host() -> str:
    click.secho("[-] Let's added Podman host:", bg='blue', fg='white', bold=False)
    click.echo("""
        Format: unix:///run/user/1000/podman/podman.sock\n
        """)

    return click.prompt("Podman host", default="unix:///run/user/1000/podman/podman.sock")


def ask_for_dev_token() -> str:
    click.secho("[-] Let's added Development bot token:", bg='blue', fg='white', bold=False)
    click.echo("""
        Format: 1234567890:FFGGEWGLKxOSLNwoLY7ADlFTt3TjtlrEcYl7hg\n
        """)

    return click.prompt("Development bot token", default="")


def ask_for_prod_token() -> str:
    click.secho("[-] Let's added Production bot token:", bg='blue', fg='white', bold=False)
    click.echo("""
        Format: 1234567890:FFGGEWGLKxOSLNwoLY7ADlFTt3TjtlrEcYl7hg\n
        """)

    return click.prompt("Production bot token")


def create_dot_env() -> None:
    dev_token = ask_for_dev_token()
    prod_token = ask_for_prod_token()
    user_id = ask_for_user_id()
    docker_host = ask_for_docker_host()
    podman_host = ask_for_podman_host()

    variables: dict = {
        "dev_token": dev_token,
        "prod_token": prod_token,
        "user_id": user_id,
        "docker_host": docker_host,
        "podman_host": podman_host,
    }

    filesystem.set_file(
        APP_ENV_FILE,
        Template(default_env_tpl.ENV_TEMPLATE).substitute(variables)
    )

    click.secho("[+] %s created." % APP_ENV_FILE, fg="green", bold=True)


@click.command()
def build_config() -> None:
    click.secho("*** Starting build default .pytmbotenv ***", fg="green", bold=True)

    # .env
    if filesystem.has_file(APP_ENV_FILE):
        click.secho("Looks like you already have .pytmbotenv, if you need reconfigure bot, remove it.", blink=True,
                    fg="yellow", bold=True)
    else:
        create_dot_env()

    click.secho("All done. Now you can build Docker image and run bot.", blink=True, bg='blue', fg='white', bold=True)


if __name__ == '__main__':
    build_config()
