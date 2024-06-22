from dataclasses import dataclass
from typing import Optional


@dataclass
class ContainerData:
    """
    Data class to store container id.

    Attributes:
        container_id (Optional[list]): A list of container ids.
    """
    container_id: Optional[list] = None
