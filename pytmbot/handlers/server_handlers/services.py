#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.

Services Handler - Provides comprehensive system services status information
with safe subprocess execution and fallback mechanisms.
"""

import json
import shlex
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Final, TypedDict

from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import psutil_adapter, em, settings
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


class ServiceStatus(TypedDict):
    """Type definition for service status"""

    active: str
    enabled: str
    exists: bool


class SystemdServicesInfo(TypedDict):
    """Type definition for systemd services information"""

    total_services: int
    active_services: int
    failed_services: int
    critical_services: Dict[str, ServiceStatus]
    available: bool


class AlpineServicesInfo(TypedDict):
    """Type definition for Alpine services information"""

    total_services: int
    started_services: int
    stopped_services: int
    services_by_runlevel: Dict[str, Dict[str, List[str]]]
    available: bool
    type: str


class CacheInfo(TypedDict):
    """Type definition for cache information"""

    cache_ttl: int
    cached_entries: int


class ServicesAdapter:
    """Safe adapter for getting system services information with smart caching"""

    # Whitelist of safe systemctl commands and arguments
    SAFE_SYSTEMCTL_COMMANDS: Final[Dict[str, List[str]]] = {
        "list-units": ["--type=service", "--output=json", "--no-pager", "--quiet"],
        "is-active": ["--quiet"],
        "is-enabled": ["--quiet"],
        "show": ["--property=ActiveState,SubState,LoadState", "--no-pager", "--quiet"],
    }

    # Critical services to monitor (configurable)
    CRITICAL_SERVICES: Final[List[str]] = [
        "ssh",
        "sshd",
        "nginx",
        "apache2",
        "httpd",
        "postgresql",
        "mysql",
        "mariadb",
        "redis",
        "mongodb",
        "NetworkManager",
        "systemd-networkd",
        "firewalld",
        "ufw",
    ]

    # Cache settings
    CACHE_TTL: Final[int] = 30  # 30 seconds cache

    def __init__(self) -> None:
        self.systemd_available: bool = self._check_systemd_availability()

        # Simple cache storage with proper typing
        self._cache: Dict[str, Any] = {}
        self._cache_timestamps: Dict[str, float] = {}

    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cache entry is still valid"""
        if cache_key not in self._cache_timestamps:
            return False

        return (time.time() - self._cache_timestamps[cache_key]) < self.CACHE_TTL

    def _get_from_cache(self, cache_key: str) -> Optional[Any]:
        """Get data from cache if valid"""
        if self._is_cache_valid(cache_key):
            logger.debug(f"Using cached data for {cache_key}")
            return self._cache.get(cache_key)
        return None

    def _set_cache(self, cache_key: str, data: Any) -> None:
        """Set data to cache with timestamp"""
        self._cache[cache_key] = data
        self._cache_timestamps[cache_key] = time.time()
        logger.debug(f"Cached data for {cache_key}")

    def _clear_expired_cache(self) -> None:
        """Clean up expired cache entries"""
        current_time = time.time()
        expired_keys = [
            key
            for key, timestamp in self._cache_timestamps.items()
            if (current_time - timestamp) >= self.CACHE_TTL
        ]

        for key in expired_keys:
            self._cache.pop(key, None)
            self._cache_timestamps.pop(key, None)

        if expired_keys:
            logger.debug(f"Cleared {len(expired_keys)} expired cache entries")

    def _check_systemd_availability(self) -> bool:
        """Safely check if systemd is available (including from Alpine container)"""
        try:
            # First, try direct systemctl access
            systemctl_paths = [
                "/usr/bin/systemctl",
                "/bin/systemctl",
                "/sbin/systemctl",
            ]

            for path in systemctl_paths:
                path_obj = Path(path)
                if path_obj.exists() and path_obj.is_file():
                    if self._test_systemctl_command([path]):
                        return True

            # If no systemctl in container, try to access host systemctl
            host_paths = ["/host/usr/bin/systemctl", "/host/bin/systemctl"]
            for path in host_paths:
                path_obj = Path(path)
                if path_obj.exists():
                    if self._test_systemctl_command([path]):
                        return True

            # Try nsenter to access host namespace (if available)
            return self._can_use_nsenter()

        except Exception as e:
            logger.warning(f"Error checking systemd availability: {e}")
            return False

    @staticmethod
    def _test_systemctl_command(command: List[str]) -> bool:
        """Test if systemctl command works"""
        try:
            result = subprocess.run(
                command + ["--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    @staticmethod
    def _can_use_nsenter() -> bool:
        """Check if we can use nsenter to access host systemd"""
        try:
            # Check if nsenter is available and we can access host PID 1
            nsenter_paths = ["/usr/bin/nsenter", "/bin/nsenter", "/sbin/nsenter"]

            for nsenter_path in nsenter_paths:
                if not Path(nsenter_path).exists():
                    continue

                # Try to check if we can access host PID namespace
                result = subprocess.run(
                    [nsenter_path, "-t", "1", "-p", "-m", "systemctl", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if result.returncode == 0:
                    return True

            return False

        except Exception as e:
            logger.warning(f"Error checking nsenter availability: {e}")
            return False

    @staticmethod
    def _get_systemctl_command_prefix() -> List[str]:
        """Get the appropriate command prefix for systemctl access"""
        # Try direct systemctl first
        systemctl_paths = ["/usr/bin/systemctl", "/bin/systemctl", "/sbin/systemctl"]
        for path in systemctl_paths:
            if Path(path).exists():
                return [path]

        # Try host mounted systemctl
        host_paths = ["/host/usr/bin/systemctl", "/host/bin/systemctl"]
        for path in host_paths:
            if Path(path).exists():
                return [path]

        # Try nsenter to host namespace
        nsenter_paths = ["/usr/bin/nsenter", "/bin/nsenter", "/sbin/nsenter"]
        for nsenter_path in nsenter_paths:
            if Path(nsenter_path).exists():
                return [nsenter_path, "-t", "1", "-p", "-m", "systemctl"]

        return ["systemctl"]  # Fallback

    @staticmethod
    def _safe_subprocess_run(
        command: List[str], timeout: int = 10
    ) -> Optional[subprocess.CompletedProcess[str]]:
        """Safely execute subprocess with validation"""
        try:
            # Validate command structure
            if not command or not isinstance(command, list):
                logger.warning(f"Invalid command structure: {command}")
                return None

            # Ensure command is properly escaped (only if needed)
            safe_command = [
                shlex.quote(str(arg)) if " " in str(arg) else str(arg)
                for arg in command
            ]

            # Execute with strict limits
            result = subprocess.run(
                safe_command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                shell=False,  # Never use shell=True
                env={
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/host/usr/bin:/host/bin",
                    "LC_ALL": "C",  # Ensure consistent output format
                },
            )

            return result

        except subprocess.TimeoutExpired:
            logger.warning(f"Command timeout: {' '.join(command)}")
            return None
        except (OSError, ValueError) as e:
            logger.error(f"Subprocess error: {e}")
            return None

    def get_systemd_services(self) -> Optional[SystemdServicesInfo]:
        """Get systemd services information safely with caching"""
        if not self.systemd_available:
            return None

        # Check cache first
        cache_key = "systemd_services"
        cached_data = self._get_from_cache(cache_key)
        if cached_data is not None:
            return cached_data

        try:
            # Get appropriate systemctl command
            systemctl_cmd = self._get_systemctl_command_prefix()
            command = systemctl_cmd + self.SAFE_SYSTEMCTL_COMMANDS["list-units"]
            result = self._safe_subprocess_run(command)

            if not result or result.returncode != 0:
                logger.warning("Failed to get systemd services list")
                return None

            # Parse JSON output
            try:
                services_data = json.loads(result.stdout)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse systemctl JSON output: {e}")
                return None

            # Process services data
            active_count = 0
            failed_count = 0
            critical_services_status: Dict[str, ServiceStatus] = {}

            for service in services_data:
                service_active = service.get("active", "")
                if service_active == "active":
                    active_count += 1
                elif service_active == "failed":
                    failed_count += 1

            # Check critical services (batch operation to minimize systemctl calls)
            for service_name in self.CRITICAL_SERVICES:
                status = self._get_service_status(service_name)
                if status:
                    critical_services_status[service_name] = status

            result_data: SystemdServicesInfo = {
                "total_services": len(services_data),
                "active_services": active_count,
                "failed_services": failed_count,
                "critical_services": critical_services_status,
                "available": True,
            }

            # Cache the result
            self._set_cache(cache_key, result_data)
            return result_data

        except Exception as e:
            logger.error(f"Error getting systemd services: {e}")
            return None

    def _get_service_status(self, service_name: str) -> Optional[ServiceStatus]:
        """Get detailed status of a specific service"""
        try:
            # Validate service name (only alphanumeric, dash, underscore, dot)
            cleaned_name = (
                service_name.replace("-", "").replace("_", "").replace(".", "")
            )
            if not cleaned_name.isalnum():
                logger.warning(f"Invalid service name: {service_name}")
                return None

            # Get service status
            systemctl_cmd = self._get_systemctl_command_prefix()
            is_active_cmd = (
                systemctl_cmd
                + ["is-active", service_name]
                + self.SAFE_SYSTEMCTL_COMMANDS["is-active"]
            )
            is_enabled_cmd = (
                systemctl_cmd
                + ["is-enabled", service_name]
                + self.SAFE_SYSTEMCTL_COMMANDS["is-enabled"]
            )

            active_result = self._safe_subprocess_run(is_active_cmd)
            enabled_result = self._safe_subprocess_run(is_enabled_cmd)

            if not active_result or not enabled_result:
                return None

            return ServiceStatus(
                active=active_result.stdout.strip(),
                enabled=enabled_result.stdout.strip(),
                exists=active_result.returncode != 4,  # 4 means unit not found
            )

        except Exception as e:
            logger.error(f"Error getting service status for {service_name}: {e}")
            return None

    def get_alpine_services(self) -> Optional[AlpineServicesInfo]:
        """Get Alpine Linux OpenRC services information with caching"""
        # Check cache first
        cache_key = "alpine_services"
        cached_data = self._get_from_cache(cache_key)
        if cached_data is not None:
            return cached_data

        try:
            # Check if we're in Alpine and have access to rc-status
            rc_status_paths = [
                "/sbin/rc-status",
                "/usr/sbin/rc-status",
                "/bin/rc-status",
            ]
            rc_status_path: Optional[str] = None

            for path in rc_status_paths:
                if Path(path).exists():
                    rc_status_path = path
                    break

            if not rc_status_path:
                return None

            # Get OpenRC services status
            result = subprocess.run(
                [rc_status_path, "-a"],  # Show all runlevels
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                env={"LC_ALL": "C"},
            )

            if result.returncode != 0:
                logger.warning(f"rc-status failed with code {result.returncode}")
                return None

            # Parse rc-status output
            services_info = self._parse_rc_status_output(result.stdout)

            result_data: AlpineServicesInfo = {
                "total_services": services_info.get("total", 0),
                "started_services": services_info.get("started", 0),
                "stopped_services": services_info.get("stopped", 0),
                "services_by_runlevel": services_info.get("by_runlevel", {}),
                "available": True,
                "type": "openrc",
            }

            # Cache the result
            self._set_cache(cache_key, result_data)
            return result_data

        except Exception as e:
            logger.error(f"Error getting Alpine services: {e}")
            return None

    @staticmethod
    def _parse_rc_status_output(output: str) -> Dict[str, Any]:
        """Parse rc-status command output"""
        services_info = {"total": 0, "started": 0, "stopped": 0, "by_runlevel": {}}

        current_runlevel: Optional[str] = None

        for line in output.split("\n"):
            line = line.strip()
            if not line:
                continue

            # Detect runlevel headers
            if line.startswith("Runlevel:"):
                current_runlevel = line.split(":", 1)[1].strip()
                services_info["by_runlevel"][current_runlevel] = {
                    "started": [],
                    "stopped": [],
                }
                continue

            # Parse service status
            if current_runlevel and " [ " in line:
                service_name = line.split("[")[0].strip()

                if "[ started ]" in line:
                    services_info["started"] += 1
                    services_info["total"] += 1
                    services_info["by_runlevel"][current_runlevel]["started"].append(
                        service_name
                    )
                elif "[ stopped ]" in line or "[ crashed ]" in line:
                    services_info["stopped"] += 1
                    services_info["total"] += 1
                    services_info["by_runlevel"][current_runlevel]["stopped"].append(
                        service_name
                    )

        return services_info

    def get_services_summary(self) -> Dict[str, Any]:
        """Get comprehensive services summary with automatic cache cleanup"""
        # Clean up expired cache entries
        self._clear_expired_cache()

        summary = {
            "systemd": self.get_systemd_services(),
            "alpine": self.get_alpine_services(),
            "available_sources": [],
            "cache_info": CacheInfo(
                cache_ttl=self.CACHE_TTL, cached_entries=len(self._cache)
            ),
        }

        # Determine available sources
        available_sources = []
        if summary["systemd"]:
            available_sources.append("systemd")
        if summary["alpine"]:
            available_sources.append("alpine")

        summary["available_sources"] = available_sources
        return summary


# regexp="Services" or "📊 Services"
@logger.session_decorator
def handle_services_status(message: Message, bot: TeleBot) -> None | Message:
    """Handle services status request with comprehensive information"""

    emojis = {
        "gear": em.get_emoji("gear"),
        "green_circle": em.get_emoji("green_circle"),
        "red_circle": em.get_emoji("red_circle"),
        "yellow_circle": em.get_emoji("yellow_circle"),
        "desktop_computer": em.get_emoji("desktop_computer"),
        "warning": em.get_emoji("warning"),
    }

    if message.from_user.id not in settings.access_control.allowed_user_ids:
        bot.send_message(
            message.chat.id,
            f"{emojis.get('warning', '⚠️')} I have checked and you do not have access rights to execute this command. I'm sorry...",
        )

    # Initialize adapter as singleton
    services_adapter = ServicesAdapter()

    try:
        bot.send_chat_action(message.chat.id, "typing")

        # Get services information
        services_info = services_adapter.get_services_summary()

        if not services_info.get("available_sources"):
            logger.warning("No services information sources available")
            return bot.send_message(
                message.chat.id,
                text=f"{emojis['warning']} No services information available. "
                "SystemD, OpenRC are not accessible from this container.",
            )

        # Prepare context for template
        template_context = {
            "services_data": services_info,
            "has_systemd": bool(services_info.get("systemd")),
            "has_alpine": bool(services_info.get("alpine")),
            **emojis,
        }

        # Compile template
        bot_answer = Compiler.quick_render(
            template_name="b_services_status.jinja2", context=template_context, **emojis
        )

        bot.send_message(message.chat.id, text=bot_answer, parse_mode="Markdown")

    except Exception as error:
        bot.send_message(
            message.chat.id,
            f"{emojis.get('warning', '⚠️')} An error occurred while processing the services status.",
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling services status",
                error_code="HAND_SERVICES_001",
                metadata={
                    "exception": str(error),
                    "systemd_available": services_adapter.systemd_available,
                },
            )
        )
