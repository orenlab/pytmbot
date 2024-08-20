#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from datetime import datetime

from pytmbot.adapters.docker._adapter import DockerAdapter
from pytmbot.logs import bot_logger
from pytmbot.utils.utilities import set_naturalsize, set_naturaltime


def fetch_image_details():
    """
    Fetches image details from the Docker client.

    This function uses the DockerAdapter to connect to the Docker client and fetches a list of images.
    It then constructs a list of dictionaries, where each dictionary represents an image and contains the following keys:
        - 'id': The short ID of the image.
        - 'name': The name of the image, or "N/A" if not available.
        - 'tags': The tags of the image, or "N/A" if not available.
        - 'architecture': The architecture of the image, or "N/A" if not available.
        - 'os': The OS of the image, or "N/A" if not available.
        - 'size': The size of the image, formatted using set_naturalsize.
        - 'created': The creation time of the image, formatted using set_naturaltime, or "N/A" if not available.

    Returns:
        A list of dictionaries representing the image details, or None if an exception occurs.
    """
    try:
        with DockerAdapter() as adapter:
            images = adapter.images.list(all=True)

            image_details = [
                {
                    'id': image.short_id,
                    'name': image.attrs.get('RepoTags', "N/A"),
                    'tags': image.tags or "N/A",
                    'architecture': image.attrs.get('Architecture', "N/A"),
                    'os': image.attrs.get('Os', "N/A"),
                    'size': set_naturalsize(image.attrs.get('Size', 0)),
                    'created': set_naturaltime(datetime.fromisoformat(image.attrs.get('Created'))) or "N/A",
                }
                for image in images
            ]

            return image_details

    except Exception as e:
        bot_logger.error(f"Failed to fetch image details: {e}")
        return None
