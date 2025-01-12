import argparse
from functools import lru_cache


@lru_cache(maxsize=None)
def parse_cli_args() -> argparse.Namespace:
    """
    Parses command line arguments using `argparse`.

    Returns:
        argparse.Namespace: The parsed command line arguments.
    """
    parser = argparse.ArgumentParser(description="PyTMBot CLI")

    parser.add_argument(
        "--mode",
        choices=["dev", "prod"],
        default="prod",
        help="PyTMBot mode (dev or prod)",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "ERROR"],
        default="INFO",
        help="Log level",
    )

    parser.add_argument(
        "--colorize_logs",
        choices=["True", "False"],
        default="True",
        help="Colorize logs",
    )

    parser.add_argument(
        "--webhook",
        choices=["True", "False"],
        default="False",
        help="Start in webhook mode",
    )

    parser.add_argument(
        "--socket_host",
        default="127.0.0.1",
        help="Socket host for listening in webhook mode",
    )

    parser.add_argument(
        "--plugins", nargs="+", default=[], help="List of plugins to load"
    )

    parser.add_argument(
        "--health_check",
        type=bool,
        default=False,
        help="Enable or disable health check"
    )

    args = parser.parse_args()
    return args
