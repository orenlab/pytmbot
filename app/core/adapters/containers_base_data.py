from dataclasses import dataclass


@dataclass
class ContainerData:
    """
    Data class to store container id.

    Attributes:
        container_id (str): The ID of the container.
    """
    container_id: list = None
