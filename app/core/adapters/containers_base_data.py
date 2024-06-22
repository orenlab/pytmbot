from dataclasses import dataclass
from typing import Optional


@dataclass
class ContainerData:
    """
    Data class to store container id.

    Attributes:
        container_id (str): The ID of the container.
    """
    container_id: Optional[list] = None
