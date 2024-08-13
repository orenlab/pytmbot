#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

try:
    import click
except ImportError:
    raise ImportError("Error loading 'click' package. Install it!")
from string import Template

import bot_cli.cfg_templates.env as default_env_tpl
from bot_cli import fs as filesystem
from bot_cli.generate_salt import generate_random_auth_salt

APP_ENV_FILE = '.pytmbotenv'


def ask_for_user_id() -> str:
    """
    Prompts the user to enter one or more user IDs and returns them as a string.

    Returns:
        str: A comma-separated string of user IDs.
    """
    # Display a message to the user indicating the format of the user IDs
    click.secho("[-] Let's added allowed user ID`s:", bg='blue', fg='white', bold=False)
    click.echo("""
        Format (one user ID): 000000000000\n
        Format (more than one user ID): 000000000000, 000000000000, 000000000000\n
        """)

    # Prompt the user to enter one or more user IDs
    return click.prompt("User IDS")


def ask_for_docker_host() -> str:
    """
    Prompts the user to enter the Docker host and returns the input.

    Returns:
        str: The Docker host entered by the user.
    """
    # Display a message to the user indicating the purpose of the input
    click.secho("[-] Let's add the Docker host:", bg='blue', fg='white', bold=False)

    # Provide the format for the input
    click.echo("""
        Format: unix:///var/run/docker.sock\n
        """)

    # Prompt the user to enter the Docker host and provide a default value
    return click.prompt("Docker host", default="unix:///var/run/docker.sock")


def ask_for_dev_token() -> str:
    """
    Prompts the user to enter the development bot token.

    Returns:
        str: The development bot token entered by the user.
    """
    # Display a message to the user indicating the purpose of the input
    click.secho("[-] Let's added Development bot token:", bg='blue', fg='white', bold=False)

    # Provide the format for the input
    click.echo("""
        Format: 1234567890:FFGGEWGLKxOSLNwoLY7ADlFTt3TjtlrEcYl7hg\n
        """)

    # Prompt the user to enter the development bot token and provide a default value
    return click.prompt("Development bot token", default="")


def ask_for_prod_token() -> str:
    """
    Prompts the user to enter the production bot token.

    Returns:
        str: The production bot token entered by the user.
    """
    # Display a message to the user indicating the purpose of the input
    click.secho("[-] Let's added Production bot token:", bg='blue', fg='white', bold=False)

    # Provide the format for the input
    click.echo("""
        Format: 1234567890:FFGGEWGLKxOSLNwoLY7ADlFTt3TjtlrEcYl7hg\n
        """)

    # Prompt the user to enter the production bot token and provide a default value
    return click.prompt("Production bot token")


def ask_for_admin_user_id() -> str:
    """
    Prompts the user to enter one or more user IDs and returns them as a string.

    Returns:
        str: A comma-separated string of user IDs.
    """
    # Display a message to the user indicating the format of the user IDs
    click.secho("[-] Let's added admin user ID`s:", bg='blue', fg='white', bold=False)
    click.echo("""
        Format (one user ID): 000000000000\n
        Format (more than one user ID): 000000000000, 000000000000, 000000000000\n
        """)

    # Prompt the user to enter one or more user IDs
    return click.prompt("User IDS")


def ask_for_auth_salt() -> str:
    """
    Prompts the user to enter the auth salt.

    Returns:
        str: The auth salt entered by the user.
    """
    # Display a message to the user indicating the purpose of the input
    click.secho("[-] Let's added auth salt:", bg='blue', fg='white', bold=False)

    # Provide the format for the input
    click.echo("""
        Leave the field blank to automatically generate a random salt.\n
        """)

    # Prompt the user to enter the auth salt and provide a default value
    return click.prompt("Auth salt", default=generate_random_auth_salt())


def create_dot_env() -> None:
    """
    Creates a .env file with bot tokens, user ids, and host information.

    This function prompts the user to enter the development bot token, production bot token,
    user id, Docker host, and Podman host. It then creates a dictionary with these values
    and uses it to create a .env file with the appropriate format.

    Returns:
        None
    """
    # Prompt the user for the development bot token
    dev_token = ask_for_dev_token()

    # Prompt the user for the production bot token
    prod_token = ask_for_prod_token()

    # Prompt the user for the user id
    user_id = ask_for_user_id()

    # Prompt the user for the Podman host
    admin_id = ask_for_admin_user_id()

    # Prompt the user for the Docker host
    docker_host = ask_for_docker_host()

    # Prompt the user for the auth salt
    auth_salt = ask_for_auth_salt()

    # Create a dictionary with the variables
    variables: dict = {
        "dev_token": dev_token,
        "prod_token": prod_token,
        "user_id": user_id,
        "admin_id": admin_id,
        "docker_host": docker_host,
        "auth_salt": auth_salt
    }

    # Create the .env file with the variables
    filesystem.set_file(
        APP_ENV_FILE,
        Template(default_env_tpl.ENV_TEMPLATE).substitute(variables)
    )

    # Print a success message
    click.secho("[+] %s created." % APP_ENV_FILE, fg="green", bold=True)


@click.command()
def build_config() -> None:
    """
    Builds the default .pytmbotenv file.

    If the file already exists, it prompts the user to remove it before proceeding.
    After the file is created, it prints a success message.
    """

    # Print a message indicating the start of the build process
    click.secho("*** Starting build default .pytmbotenv ***", fg="green", bold=True)

    # Check if the .pytmbotenv file already exists
    if filesystem.has_file(APP_ENV_FILE):
        # If the file exists, prompt the user to remove it before proceeding
        click.secho("Looks like you already have .pytmbotenv, if you need to reconfigure the bot, remove it.",
                    blink=True, fg="yellow", bold=True)
    else:
        # If the file does not exist, create it
        create_dot_env()

    # Print a success message
    click.secho("All done. Now you can build Docker image and run the bot.", blink=True, bg='blue', fg='white',
                bold=True)


if __name__ == '__main__':
    build_config()
