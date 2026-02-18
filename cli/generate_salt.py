#!/usr/bin/env python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.

CLI utility to generate authentication salts for pyTMBot.
"""

from __future__ import annotations

import argparse
import base64
import secrets
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

Encoding = Literal["base32", "base64", "hex"]


def _format_utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


class SaltGenerator:
    """Generate cryptographically secure salts for auth/TOTP usage."""

    encoding_options: Final[dict[Encoding, Callable[[bytes], bytes]]]

    def __init__(self) -> None:
        self.encoding_options = {
            "base32": base64.b32encode,
            "base64": base64.b64encode,
            "hex": lambda payload: payload.hex().encode("utf-8"),
        }

    def generate_salt(self, length: int = 32, encoding: Encoding = "base32") -> str:
        """Generate a cryptographically secure random salt."""
        random_bytes = secrets.token_bytes(length)
        encoder = self.encoding_options[encoding]

        if encoding == "hex":
            return random_bytes.hex().upper()
        return encoder(random_bytes).decode("utf-8")

    def display_header(self) -> None:
        print("=" * 72)
        print("pyTMBot - Secure Authentication Salt Generator")
        print("=" * 72)

    def display_salt_info(self, salt: str, length: int, encoding: Encoding) -> None:
        print("\nGenerated Salt")
        print("-" * 72)
        print(salt)

        print("\nSalt Information")
        print("-" * 72)
        print(f"Byte length:     {length}")
        print(f"Encoding:        {encoding.upper()}")
        print(f"Final length:    {len(salt)}")
        print(f"Entropy:         {length * 8} bits")
        print(f"Security level:  {'HIGH' if length >= 32 else 'BASIC'}")

    def display_config_template(self, salt: str) -> None:
        yaml_config = f"""# pyTMBot Configuration - Auth Salt Section
# Generated on: {_format_utc_now()}
# Salt length: {len(salt)} characters

# Salt for TOTP (Time-Based One-Time Password) generation (REQUIRED)
auth_salt:
  - '{salt}'"""

        print("\nYAML Configuration")
        print("-" * 72)
        print(yaml_config)

    def _prompt_yes_no(self, prompt: str, default: bool = True) -> bool:
        suffix = "[Y/n]" if default else "[y/N]"
        value = input(f"{prompt} {suffix}: ").strip().lower()
        if not value:
            return default
        return value in {"y", "yes"}

    def _prompt_int(self, prompt: str, default: int, min_value: int = 1) -> int:
        while True:
            value = input(f"{prompt} [{default}]: ").strip()
            if not value:
                return default
            try:
                parsed = int(value)
            except ValueError:
                print("Please enter a valid integer.")
                continue
            if parsed < min_value:
                print(f"Value must be >= {min_value}.")
                continue
            return parsed

    def _prompt_choice(self, prompt: str, choices: dict[str, str], default: str) -> str:
        while True:
            print(prompt)
            for key, description in choices.items():
                marker = " (default)" if key == default else ""
                print(f"  {key}) {description}{marker}")
            value = input("Select option: ").strip() or default
            if value in choices:
                return value
            print("Invalid choice, try again.")

    def save_to_file(self, salt: str) -> None:
        """Save generated salt in one of supported formats."""
        if not self._prompt_yes_no("Save salt to file?", default=True):
            return

        choice = self._prompt_choice(
            "Choose save format:",
            {
                "1": "Plain salt",
                "2": "YAML config section",
                "3": "ENV format",
                "4": "All formats",
            },
            default="2",
        )

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

        try:
            if choice == "1":
                filename = Path(f"auth_salt_{timestamp}.txt")
                filename.write_text(salt, encoding="utf-8")
                print(f"Saved: {filename.name}")
                return

            if choice == "2":
                filename = Path(f"pytmbot_auth_{timestamp}.yml")
                filename.write_text(
                    "\n".join(
                        [
                            "# pyTMBot Configuration - Auth Salt Section",
                            f"# Generated on: {_format_utc_now()}",
                            "",
                            "# Salt for TOTP (Time-Based One-Time Password) generation (REQUIRED)",
                            "auth_salt:",
                            f"  - '{salt}'",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
                print(f"Saved: {filename.name}")
                return

            if choice == "3":
                filename = Path(f"auth_salt_{timestamp}.env")
                filename.write_text(
                    "\n".join(
                        [
                            "# pyTMBot Authentication Salt",
                            f"# Generated on: {_format_utc_now()}",
                            "",
                            f"AUTH_SALT='{salt}'",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
                print(f"Saved: {filename.name}")
                return

            files: list[Path] = []

            plain_file = Path(f"auth_salt_{timestamp}.txt")
            plain_file.write_text(salt, encoding="utf-8")
            files.append(plain_file)

            yaml_file = Path(f"pytmbot_auth_{timestamp}.yml")
            yaml_file.write_text(
                "\n".join(
                    [
                        "# pyTMBot Configuration - Auth Salt Section",
                        f"# Generated on: {_format_utc_now()}",
                        "",
                        "auth_salt:",
                        f"  - '{salt}'",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            files.append(yaml_file)

            env_file = Path(f"auth_salt_{timestamp}.env")
            env_file.write_text(
                "\n".join(
                    [
                        "# pyTMBot Authentication Salt",
                        f"AUTH_SALT='{salt}'",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            files.append(env_file)

            print("Saved all formats:")
            for file_path in files:
                print(f"  - {file_path.name}")

        except OSError as error:
            print(f"Error saving file: {error}")

    def generate_multiple_salts(self) -> None:
        configs: list[tuple[int, Encoding, str, str]] = [
            (16, "hex", "Compact Hex Salt", "For lightweight applications"),
            (32, "base32", "Standard Base32 Salt", "Recommended for pyTMBot"),
            (48, "base64", "Premium Base64 Salt", "Maximum security level"),
            (64, "hex", "Ultra Secure Hex Salt", "Enterprise-grade protection"),
        ]

        print("\nMultiple Salt Generation")
        print("-" * 72)
        for length, encoding, name, description in configs:
            salt = self.generate_salt(length, encoding)
            truncated_salt = salt[:60] + "..." if len(salt) > 63 else salt
            print(f"\n{name}")
            print(f"  Description: {description}")
            print(f"  Encoding:    {encoding}")
            print(f"  Length:      {len(salt)} chars")
            print(f"  Salt:        {truncated_salt}")

    def interactive_mode(self) -> None:
        self.display_header()

        print("\nThis wizard generates secure salts for pyTMBot TOTP authentication.")
        length = self._prompt_int(
            "Salt length in bytes (recommended 32)",
            default=32,
            min_value=1,
        )

        encoding_choice = self._prompt_choice(
            "Choose encoding:",
            {
                "1": "base32 (recommended)",
                "2": "base64",
                "3": "hex",
            },
            default="1",
        )

        encoding_map: dict[str, Encoding] = {
            "1": "base32",
            "2": "base64",
            "3": "hex",
        }
        encoding = encoding_map[encoding_choice]

        salt = self.generate_salt(length, encoding)

        self.display_salt_info(salt, length, encoding)
        self.display_config_template(salt)

        if self._prompt_yes_no("Generate additional salts with predefined configs?", default=False):
            self.generate_multiple_salts()

        self.save_to_file(salt)
        print("\nDone.")


def create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate secure authentication salts for pyTMBot",
        formatter_class=argparse.HelpFormatter,
    )

    parser.add_argument(
        "-l",
        "--length",
        type=int,
        default=32,
        help="Salt length in bytes (default: 32)",
    )
    parser.add_argument(
        "-e",
        "--encoding",
        choices=["base32", "base64", "hex"],
        default="base32",
        help="Encoding format (default: base32)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Quiet mode (output only salt)",
    )
    parser.add_argument(
        "-m",
        "--multiple",
        action="store_true",
        help="Generate multiple salts with predefined configurations",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Run interactive mode",
    )

    return parser


def _validate_length(length: int) -> None:
    if length <= 0:
        raise ValueError("Salt length must be greater than 0")


def _normalize_encoding(raw_encoding: str) -> Encoding:
    if raw_encoding == "base32":
        return "base32"
    if raw_encoding == "base64":
        return "base64"
    if raw_encoding == "hex":
        return "hex"
    raise ValueError(f"Unsupported encoding: {raw_encoding}")


def main() -> None:
    parser = create_argument_parser()
    args = parser.parse_args()

    generator = SaltGenerator()

    try:
        _validate_length(args.length)

        encoding = _normalize_encoding(args.encoding)

        if args.interactive:
            generator.interactive_mode()
        elif args.multiple:
            generator.display_header()
            generator.generate_multiple_salts()
        elif args.quiet:
            print(generator.generate_salt(args.length, encoding))
        else:
            generator.display_header()
            salt = generator.generate_salt(args.length, encoding)
            generator.display_salt_info(salt, args.length, encoding)
            generator.display_config_template(salt)
            generator.save_to_file(salt)

    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(0)
    except Exception as error:
        print(f"\nUnexpected error: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
