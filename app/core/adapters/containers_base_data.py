from dataclasses import dataclass
from typing import Optional

from telebot.callback_data import CallbackData


@dataclass
class ContainerData:
    """
    Data class to store container id.

    Attributes:
        container_id (Optional[list]): A list of container ids.
    """
    container_id: Optional[list] = None


class ContainersFactory:
    """
    This class is responsible for creating callback data for containers.
    It uses the CallbackData class from the telebot library.
    """
    containers_factory = CallbackData('container_id', prefix='container_name')
