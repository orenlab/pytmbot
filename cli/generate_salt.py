#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.

Enhanced CLI Salt Generator with Rich interface
"""

import argparse
import base64
import secrets
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

from rich import box
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, IntPrompt
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text


class SaltGenerator:
    """Enhanced salt generator with Rich CLI interface."""

    def __init__(self) -> None:
        self.console = Console()
        self.encoding_options: dict[Literal['base32', 'base64', 'hex'], Callable[[bytes], bytes]] = {
            'base32': base64.b32encode,
            'base64': base64.b64encode,
            'hex': lambda payload: payload.hex().encode('utf-8')
        }

    def generate_salt(
            self,
            length: int = 32,
            encoding: Literal['base32', 'base64', 'hex'] = 'base32'
    ) -> str:
        """
        Generate a cryptographically secure random salt.

        Args:
            length: The length of the salt in bytes (default: 32)
            encoding: The encoding format (default: 'base32')

        Returns:
            The generated authentication salt as a string
        """
        random_bytes = secrets.token_bytes(length)
        encoder = self.encoding_options[encoding]

        if encoding == 'hex':
            return random_bytes.hex().upper()
        else:
            return encoder(random_bytes).decode('utf-8')

    def display_header(self) -> None:
        """Display the spectacular application header."""
        # Create animated-style header
        title = Text()
        title.append("🤖 ", style="bold bright_blue")
        title.append("pyTMBot", style="bold bright_magenta")
        title.append(" 🔐", style="bold bright_blue")

        subtitle = Text()
        subtitle.append("⚡ ", style="bright_yellow")
        subtitle.append("Secure Authentication Salt Generator", style="italic bright_cyan")
        subtitle.append(" ⚡", style="bright_yellow")

        tagline = Text("🛡️ Cryptographically Strong • Docker Ready • TOTP Compatible",
                       style="dim bright_green")

        header_content = Align.center(
            Text.assemble(title, "\n", subtitle, "\n", tagline)
        )

        header_panel = Panel(
            header_content,
            box=box.DOUBLE_EDGE,
            border_style="bright_magenta",
            padding=(1, 4),
            title="[bold bright_white]🚀 Welcome to Salt Generation Station 🚀[/bold bright_white]",
            title_align="center"
        )

        self.console.print()
        self.console.print(header_panel)
        self.console.print()

    def display_salt_info(self, salt: str, length: int, encoding: str) -> None:
        """Display the generated salt with enhanced visual appeal."""

        # Create colorful info table with better alignment
        info_table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
        info_table.add_column("🔧 Property", style="bright_cyan", justify="left", width=18)
        info_table.add_column("📊 Value", style="bright_white", justify="left", width=20)
        info_table.add_column("💡 Description", style="dim", justify="left")

        info_table.add_row(
            "Byte Length",
            str(length),
            "Original random bytes"
        )
        info_table.add_row(
            "Encoding",
            encoding.upper(),
            "Text representation format"
        )
        info_table.add_row(
            "Final Length",
            str(len(salt)),
            "Encoded string characters"
        )
        info_table.add_row(
            "Entropy",
            f"{length * 8} bits",
            "Cryptographic strength"
        )
        info_table.add_row(
            "Security Level",
            "🔥 Military Grade" if length >= 32 else "⚠️ Basic",
            "Recommended: 32+ bytes"
        )

        # Create visually appealing salt display
        salt_lines = [salt[i:i + 64] for i in range(0, len(salt), 64)]
        formatted_salt = "\n".join(f"[dim]{i + 1:02d}:[/dim] [bold bright_green]{line}[/bold bright_green]"
                                   for i, line in enumerate(salt_lines))

        salt_panel = Panel(
            Align.center(formatted_salt),
            title="🔑 [bold bright_green]Generated Authentication Salt[/bold bright_green] 🔑",
            title_align="center",
            border_style="bright_green",
            box=box.DOUBLE_EDGE,
            padding=(1, 2)
        )

        info_panel = Panel(
            info_table,
            title="📋 [bold bright_blue]Salt Technical Information[/bold bright_blue] 📋",
            title_align="center",
            border_style="bright_blue",
            box=box.ROUNDED,
            padding=(1, 2)
        )

        # Display with proper spacing
        self.console.print(salt_panel)
        self.console.print()
        self.console.print(info_panel)
        self.console.print()

    def display_config_template(self, salt: str) -> None:
        """Display the YAML config template with syntax highlighting."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

        yaml_config = f"""# pyTMBot Configuration - Auth Salt Section
# Generated on: {timestamp}
# Salt length: {len(salt)} characters

# Salt for TOTP (Time-Based One-Time Password) generation (REQUIRED)
# Generate with: docker run --rm orenlab/pytmbot:latest --salt
# Or use: openssl rand -hex 32
# Or use any random 32+ character string
auth_salt:
  - '{salt}'"""

        syntax = Syntax(
            yaml_config,
            "yaml",
            theme="monokai",
            line_numbers=True,
            background_color="default"
        )

        config_panel = Panel(
            syntax,
            title="📄 [bold bright_yellow]pyTMBot YAML Configuration[/bold bright_yellow] 📄",
            title_align="center",
            border_style="bright_yellow",
            box=box.HEAVY,
            padding=(1, 2)
        )

        self.console.print(config_panel)
        self.console.print()

    def save_to_file(self, salt: str) -> None:
        """Save the salt to a file with multiple format options."""
        if not Confirm.ask("\n💾 [bold cyan]Save salt to file?[/bold cyan]", default=True):
            return

        # Ask for format
        format_table = Table(show_header=False, box=None)
        format_table.add_column("Option", style="bold magenta", width=8)
        format_table.add_column("Format", style="bright_white", width=20)
        format_table.add_column("Description", style="dim")

        format_table.add_row("1", "🔧 Plain Salt", "Just the salt value")
        format_table.add_row("2", "📄 YAML Config", "Ready-to-use config section")
        format_table.add_row("3", "🌍 ENV Format", "Environment variable format")
        format_table.add_row("4", "📋 All Formats", "Multiple files with all formats")

        self.console.print("📁 [bold]Available save formats:[/bold]")
        self.console.print(format_table)

        format_choice = IntPrompt.ask(
            "\n🎯 Choose format",
            choices=["1", "2", "3", "4"],
            default=2,
            show_choices=False
        )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        try:
            if format_choice == 1:
                filename = Path(f"auth_salt_{timestamp}.txt")
                with filename.open('w', encoding='utf-8') as f:
                    f.write(salt)

            elif format_choice == 2:
                filename = Path(f"pytmbot_auth_{timestamp}.yml")
                with filename.open('w', encoding='utf-8') as f:
                    f.write(f"""# pyTMBot Configuration - Auth Salt Section
# Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}

# Salt for TOTP (Time-Based One-Time Password) generation (REQUIRED)
auth_salt:
  - '{salt}'
""")

            elif format_choice == 3:
                filename = Path(f"auth_salt_{timestamp}.env")
                with filename.open('w', encoding='utf-8') as f:
                    f.write("# pyTMBot Authentication Salt\n")
                    f.write(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n")
                    f.write(f"AUTH_SALT='{salt}'\n")

            elif format_choice == 4:
                # Save all formats
                files = []

                # Plain salt
                plain_file = Path(f"auth_salt_{timestamp}.txt")
                with plain_file.open('w', encoding='utf-8') as f:
                    f.write(salt)
                files.append(plain_file)

                # YAML config
                yaml_file = Path(f"pytmbot_auth_{timestamp}.yml")
                with yaml_file.open('w', encoding='utf-8') as f:
                    f.write(f"""# pyTMBot Configuration - Auth Salt Section
# Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}

auth_salt:
  - '{salt}'
""")
                files.append(yaml_file)

                # ENV format
                env_file = Path(f"auth_salt_{timestamp}.env")
                with env_file.open('w', encoding='utf-8') as f:
                    f.write("# pyTMBot Authentication Salt\n")
                    f.write(f"AUTH_SALT='{salt}'\n")
                files.append(env_file)

                self.console.print("✨ [bold green]All formats saved successfully![/bold green]")
                for file in files:
                    self.console.print(f"  📄 [bold cyan]{file.name}[/bold cyan]")
                return

            self.console.print(
                f"✅ [bold green]Salt saved to[/bold green] [bold cyan]{filename.name}[/bold cyan]"
            )

        except OSError as e:
            self.console.print(f"❌ [bold red]Error saving file: {e}[/bold red]")

    def generate_multiple_salts(self) -> None:
        """Generate multiple salts with enhanced visual feedback."""
        configs = [
            (16, 'hex', "🔥 Compact Hex Salt", "For lightweight applications"),
            (32, 'base32', "🚀 Standard Base32 Salt", "Recommended for pyTMBot"),
            (48, 'base64', "💎 Premium Base64 Salt", "Maximum security level"),
            (64, 'hex', "👑 Ultra Secure Hex Salt", "Enterprise grade protection")
        ]

        title_panel = Panel(
            Align.center(Text("🎯 Multiple Salt Generation Suite", style="bold bright_magenta")),
            box=box.DOUBLE_EDGE,
            border_style="bright_magenta"
        )

        self.console.print(title_panel)
        self.console.print()

        results_table = Table(box=box.ROUNDED, show_header=True, header_style="bold bright_cyan")
        results_table.add_column("🏷️ Type", style="bright_yellow", justify="center", width=25)
        results_table.add_column("🔐 Generated Salt", style="bright_green", justify="left")
        results_table.add_column("📏 Length", style="cyan", justify="center", width=8)

        with Progress(
                SpinnerColumn("dots"),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(bar_width=None),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                console=self.console
        ) as progress:

            main_task = progress.add_task("🔄 Generating salt collection...", total=len(configs))

            for _i, (length, encoding, name, description) in enumerate(configs):
                # Individual generation task
                gen_task = progress.add_task(f"Creating {name}...", total=100)

                # Simulate realistic generation time
                for _step in range(100):
                    progress.update(gen_task, advance=1)

                salt = self.generate_salt(length, encoding)  # type: ignore

                # Add to results table
                truncated_salt = salt[:50] + "..." if len(salt) > 53 else salt
                results_table.add_row(
                    f"{name}\n[dim]{description}[/dim]",
                    f"[font=monospace]{truncated_salt}[/font]",
                    str(len(salt))
                )

                progress.update(main_task, advance=1)
                progress.remove_task(gen_task)

        self.console.print()
        results_panel = Panel(
            results_table,
            title="📊 [bold bright_blue]Generation Results[/bold bright_blue] 📊",
            title_align="center",
            border_style="bright_blue",
            box=box.HEAVY
        )
        self.console.print(results_panel)
        self.console.print()

    def interactive_mode(self) -> None:
        """Run in enhanced interactive mode."""
        self.display_header()

        # Welcome message
        welcome_text = """
🎉 Welcome to the Interactive Salt Generation Experience!

This tool will help you create cryptographically secure salts specifically
designed for pyTMBot's TOTP authentication system. Let's get started!
        """

        welcome_panel = Panel(
            Align.center(Text(welcome_text.strip(), style="bright_white")),
            title="🌟 [bold bright_green]Getting Started[/bold bright_green] 🌟",
            title_align="center",
            border_style="bright_green",
            box=box.ROUNDED
        )
        self.console.print(welcome_panel)
        self.console.print()

        # Get user preferences with better prompts
        length = IntPrompt.ask(
            "🔢 [bold cyan]Salt length in bytes[/bold cyan] [dim](32 is recommended for TOTP)[/dim]",
            default=32,
            show_default=True
        )

        # Enhanced encoding selection with fixed table
        encoding_grid = Table.grid(padding=1)
        encoding_grid.add_column(style="cyan", justify="left")
        encoding_grid.add_column(style="white")
        encoding_grid.add_column(style="dim")

        encoding_grid.add_row("1️⃣", "Base32 (Recommended)", "Perfect for YAML configs, Docker-friendly")
        encoding_grid.add_row("2️⃣", "Base64 (Compact)", "Shorter output, space-efficient")
        encoding_grid.add_row("3️⃣", "Hex (Human-readable)", "Easy to verify, debugging-friendly")

        encoding_panel = Panel(
            encoding_grid,
            title="🎨 [bold bright_yellow]Encoding Options[/bold bright_yellow] 🎨",
            title_align="center",
            border_style="bright_yellow",
            box=box.ROUNDED
        )

        self.console.print(encoding_panel)

        encoding_choice = IntPrompt.ask(
            "\n🎯 [bold magenta]Choose your encoding[/bold magenta]",
            choices=["1", "2", "3"],
            default=1,
            show_choices=False
        )

        encoding_map = {1: 'base32', 2: 'base64', 3: 'hex'}
        encoding = encoding_map[encoding_choice]

        # Generate salt with enhanced progress
        self.console.print("\n🔄 [bold]Initiating secure salt generation...[/bold]")

        with Progress(
                SpinnerColumn("aesthetic"),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(bar_width=None, complete_style="bright_green", finished_style="bright_green"),
                TextColumn("[bright_green]{task.percentage:>3.0f}%[/bright_green]"),
                console=self.console
        ) as progress:

            tasks = [
                ("🎲 Collecting entropy from system...", 25),
                ("🔐 Generating cryptographic bytes...", 35),
                ("🎨 Applying encoding transformation...", 25),
                ("✨ Finalizing secure salt...", 15)
            ]

            main_task = progress.add_task("🛡️ Creating your secure salt", total=100)

            for desc, duration in tasks:
                sub_task = progress.add_task(desc, total=duration)
                for _ in range(duration):
                    progress.update(sub_task, advance=1)
                    progress.update(main_task, advance=1)
                progress.remove_task(sub_task)

            salt = self.generate_salt(length, encoding)  # type: ignore

        self.console.print("\n🎉 [bold bright_green]Salt generation completed successfully![/bold bright_green]\n")

        # Display results
        self.display_salt_info(salt, length, encoding)
        self.display_config_template(salt)

        # Additional options with better UX
        if Confirm.ask("🔄 [bold yellow]Generate additional salts with different configs?[/bold yellow]", default=False):
            self.generate_multiple_salts()

        self.save_to_file(salt)

        # Completion message
        completion_panel = Panel(
            Align.center(
                Text.assemble(
                    ("🎊 ", "bright_yellow"),
                    ("Salt Generation Mission Accomplished!", "bold bright_green"),
                    (" 🎊", "bright_yellow"),
                    ("\n\n", ""),
                    ("Your secure salt is ready for pyTMBot deployment!", "bright_white")
                )
            ),
            title="🏆 [bold bright_green]Success![/bold bright_green] 🏆",
            title_align="center",
            border_style="bright_green",
            box=box.DOUBLE_EDGE,
            padding=(1, 4)
        )

        self.console.print()
        self.console.print(completion_panel)


def create_argument_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        description="🔐 Generate secure authentication salts for pyTMBot",
        formatter_class=argparse.HelpFormatter
    )

    parser.add_argument(
        "-l", "--length",
        type=int,
        default=32,
        help="Salt length in bytes (default: 32)"
    )

    parser.add_argument(
        "-e", "--encoding",
        choices=['base32', 'base64', 'hex'],
        default='base32',
        help="Encoding format (default: base32)"
    )

    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Quiet mode - output only the salt"
    )

    parser.add_argument(
        "-m", "--multiple",
        action="store_true",
        help="Generate multiple salts with different configurations"
    )

    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Run in interactive mode"
    )

    return parser


def main() -> None:
    """Main application entry point."""
    parser = create_argument_parser()
    args = parser.parse_args()

    generator = SaltGenerator()

    try:
        if args.interactive:
            generator.interactive_mode()
        elif args.multiple:
            generator.display_header()
            generator.generate_multiple_salts()
        elif args.quiet:
            salt = generator.generate_salt(args.length, args.encoding)  # type: ignore
            print(salt)
        else:
            generator.display_header()
            salt = generator.generate_salt(args.length, args.encoding)  # type: ignore
            generator.display_salt_info(salt, args.length, args.encoding)
            generator.display_config_template(salt)
            generator.save_to_file(salt)

    except KeyboardInterrupt:
        generator.console.print("\n👋 [yellow]Operation cancelled by user[/yellow]")
        sys.exit(0)
    except Exception as e:
        generator.console.print(f"\n💥 [red]Unexpected error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
