"""
Render every rich-HTML template with realistic data and check the markup.

These tests guard the rich message design system: valid Telegram rich HTML,
a bold paragraph title first, no section headings, tables with header rows
and consistent column alignment, footers last, and no manual list bullets.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from html.parser import HTMLParser
from pathlib import Path

import pytest

from pytmbot.parsers.compiler import Compiler
from pytmbot.parsers.filters import format_bytes
from pytmbot.utils.rich_html import find_rich_html_issues

TEMPLATES_ROOT = Path(__file__).resolve().parents[1] / "pytmbot" / "templates"

# Short conversational replies and auth prompts intentionally stay classic HTML.
CLASSIC_TEMPLATES = frozenset(
    {
        "a_access_denied.jinja2",
        "a_auth_required.jinja2",
        "a_send_totp_code.jinja2",
        "a_success.jinja2",
        "b_back.jinja2",
        "b_echo.jinja2",
        "b_none.jinja2",
    }
)

_EMOJI = "🔹"

_CONTAINER_EMOJIS = dict.fromkeys(
    (
        "thought_balloon",
        "oil_drum",
        "id",
        "package",
        "mantelpiece_clock",
        "rocket",
        "antenna_bars",
        "magnifying_glass",
    ),
    _EMOJI,
)
_IMAGE_EMOJIS = dict.fromkeys(
    (
        "thought_balloon",
        "package",
        "spouting_whale",
        "bookmark_tabs",
        "floppy_disk",
        "gear",
        "mantelpiece_clock",
        "magnifying_glass",
        "key",
        "electric_plug",
        "label",
        "minus",
    ),
    _EMOJI,
)
_IMAGE = {
    "name": "nginx",
    "id": "sha256:1a2b3c",
    "tags": ["nginx:1.29", "nginx:latest"],
    "tags_count": 2,
    "repo_digests": ["nginx@sha256:abc"],
    "repo_digests_count": 1,
    "parent_id": "N/A",
    "os": "linux",
    "architecture": "amd64",
    "variant": "v8",
    "size": "187 MB",
    "virtual_size": "187 MB",
    "shared_size": "N/A",
    "layers_count": 7,
    "rootfs_type": "layers",
    "created": "2 weeks ago",
    "created_at": "2026-09-01 10:00:00",
    "user": "root",
    "working_dir": "/",
    "stop_signal": "SIGQUIT",
    "entrypoint": ["/docker-entrypoint.sh"],
    "cmd": ["nginx", "-g", "daemon off;"],
    "shell": [],
    "healthcheck": "none",
    "exposed_ports": ["80/tcp"],
    "exposed_ports_count": 1,
    "volumes": [],
    "volumes_count": 0,
    "env_variables": ["PATH=/usr/bin", "NGINX_VERSION=1.29.1"],
    "env_variables_count": 2,
    "author": "NGINX Docker Maintainers <docker-maint@nginx.com>",
    "docker_version": "27.3.1",
    "comment": "N/A",
    "labels": {"maintainer": "NGINX <docker@nginx.com>", "__truncated__": "2 more"},
    "label_count": 3,
}
_HEALTH_CONTEXT = {
    "monitor": {
        "overall_badge": "🟢",
        "overall_status": "Operational",
        "operational": 5,
        "total": 5,
        "health_ratio_percent": 100.0,
        "duration_ms": 12.5,
        "action": "No action needed",
        "available": True,
        "components": [
            {
                "badge": "🟢",
                "component_label": "Docker",
                "status_label": "healthy",
                "latency_ms": 3.2,
                "insights": ["Socket reachable"],
            }
        ],
    },
    "overall_badge": "🟡",
    "overall_status": "Degraded",
    "health_score": 72,
    "dominant_metric": "Memory",
    "cpu_badge": "🟢",
    "cpu_percent": 12.5,
    "cpu_status": "normal",
    "memory_badge": "🟡",
    "memory_percent": 81.0,
    "memory_status": "elevated",
    "memory_used": "6.5 GB",
    "memory_available": "1.5 GB",
    "load_badge": "🟢",
    "load_1m": 0.52,
    "load_5m": 0.61,
    "load_15m": 0.7,
    "load_ratio_percent": 13.0,
    "cpu_count": 4,
    "load_status": "comfortable",
    "uptime": "3 days, 4:05:06",
    "process_total": 231,
    "docker": {
        "available": True,
        "badge": "🟢",
        "status_label": "healthy",
        "running_containers": 5,
        "stopped_containers": 1,
        "containers_total": 6,
        "running_ratio": 83.3,
        "containers_per_core": 1.5,
        "images_count": 12,
        "trend_text": "Most containers are running",
    },
    "insights": ["Memory pressure is above 80%"],
    "recommendations": ["Review memory-heavy containers"],
}


def _container_full_info() -> dict[str, object]:
    return {
        "status_badge": "🟢 running",
        "health_badge": "🟢 healthy",
        "name": "web",
        "id": "0123456789ab",
        "image_name": "nginx",
        "image_tag": "1.29",
        "uptime": "3 hours",
        "started_at": "2026-09-26 07:00:00",
        "finished_at": "N/A",
        "restart_count": 0,
        "pid": 4242,
        "resources": {
            "memory_limit": "512 MB",
            "memory_reservation": "",
            "cpu_quota": "N/A",
            "cpus_limit": "1.5",
            "cpuset_cpus": "",
            "pids_limit": "100",
            "restart_policy": "unless-stopped",
            "max_restart_count": "0",
            "memory_headroom": "400 MB",
        },
        "stats": {
            "memory": {
                "mem_usage": "112 MB",
                "mem_limit": "512 MB",
                "mem_percent": 21.9,
            },
            "cpu": {"cpu_percent": "0.4", "throttled_periods": 3},
            "network": {
                "rx_bytes": "1.2 MB",
                "tx_bytes": "300 KB",
                "rx_errors": 0,
                "tx_errors": 1,
            },
        },
        "health_failing_streak": 0,
        "health_last_checked_at": "10s ago",
        "oom_killed": False,
        "dead": False,
        "state_error": "",
        "network": {
            "network_mode": "bridge",
            "published_ports": 1,
            "declared_ports": 2,
            "ports": ["80/tcp → 0.0.0.0:8080"],
            "networks": ["bridge"],
        },
        "environment": {
            "user": "nginx",
            "working_dir": "/",
            "entrypoint": "/docker-entrypoint.sh",
            "command": "N/A",
            "env_count": 2,
            "environment_vars": ["PATH=/usr/bin", "TOKEN=********"],
        },
    }


def _container_runtime_info() -> dict[str, object]:
    return {
        "container_name": "web",
        "health_badge": "🟢 healthy",
        "health_failing_streak": 0,
        "health_last_checked_at": "10s ago",
        "health_last_log": "ok",
        "created_at": "2026-09-01",
        "started_at": "2026-09-26",
        "finished_at": "-",
        "pid": 4242,
        "exit_code": 0,
        "stop_signal": "SIGQUIT",
        "stop_timeout": "10s",
        "oom_killed": "no",
        "dead": "no",
        "state_error": "-",
        "privileged": "no",
        "read_only_rootfs": "yes",
        "oom_kill_disable": "no",
        "no_new_privileges": "yes",
        "init_process": "no",
        "security_opts_count": 1,
        "security_opts": ["no-new-privileges:true"],
        "hidden_security_opts_count": 0,
        "cap_add_text": "",
        "cap_drop_text": "ALL",
    }


def _container_networks_info() -> dict[str, object]:
    return {
        "container_name": "web",
        "network_mode": "bridge",
        "hostname": "web",
        "domainname": "-",
        "bridge_name": "docker0",
        "sandbox_id": "abc",
        "publish_all_ports": "no",
        "enable_ipv6": "no",
        "ports_count": 2,
        "ports": [
            {
                "container_port": "80/tcp",
                "is_published": True,
                "host_bindings": ["0.0.0.0:8080"],
            },
            {"container_port": "443/tcp", "is_published": False, "host_bindings": []},
        ],
        "hidden_ports_count": 0,
        "exposed_ports_count": 1,
        "exposed_ports": ["80/tcp"],
        "hidden_exposed_ports_count": 0,
        "dns_servers_count": 1,
        "dns_servers": ["1.1.1.1"],
        "hidden_dns_servers_count": 0,
        "dns_search_count": 0,
        "dns_search": [],
        "hidden_dns_search_count": 0,
        "dns_options_count": 0,
        "dns_options": [],
        "hidden_dns_options_count": 0,
        "extra_hosts_count": 0,
        "extra_hosts": [],
        "hidden_extra_hosts_count": 0,
        "links_count": 0,
        "links": [],
        "hidden_links_count": 0,
        "networks_count": 1,
        "networks": [
            {
                "name": "bridge",
                "ip_address": "172.17.0.2",
                "ip_prefix_len": 16,
                "gateway": "172.17.0.1",
                "global_ipv6_address": "-",
                "global_ipv6_prefix_len": 0,
                "ipv6_gateway": "-",
                "mac_address": "02:42:ac:11:00:02",
                "endpoint_id": "e1",
                "network_id": "n1",
                "aliases": ["web"],
                "hidden_aliases_count": 0,
            }
        ],
        "hidden_networks_count": 0,
    }


def _container_volumes_info() -> dict[str, object]:
    return {
        "container_name": "web",
        "mounts_count": 1,
        "mounts_total": 1,
        "mounts": [
            {
                "type": "bind",
                "name": "-",
                "source": "/srv/web",
                "destination": "/usr/share/nginx/html",
                "access": "ro",
                "mode": "ro",
                "propagation": "rprivate",
                "driver": "-",
            }
        ],
        "hidden_mounts_count": 0,
        "declared_volumes_count": 0,
        "declared_volumes": [],
        "hidden_declared_volumes_count": 0,
        "bind_specs_count": 1,
        "bind_specs": ["/srv/web:/usr/share/nginx/html:ro"],
        "hidden_bind_specs_count": 0,
        "volumes_from_count": 0,
        "volumes_from": [],
        "hidden_volumes_from_count": 0,
        "tmpfs_mounts_count": 0,
        "tmpfs_mounts": [],
        "hidden_tmpfs_mounts_count": 0,
    }


RICH_RENDER_CASES: dict[str, dict[str, object]] = {
    "b_about_bot.jinja2": {"context": {"username": "Den", "app_version": "0.5.0"}},
    "b_bot_update.jinja2": {
        "current_version": "v0.5.1",
        "release_date": "2026-10-01",
        "release_notes_html": "<p><b>Fixed</b></p><ul><li>Something</li></ul>",
    },
    "b_cpu.jinja2": {
        "context": {
            "cpu_percent": 12.5,
            "logical_cores": 8,
            "physical_cores": 4,
            "current_freq_mhz": 2400.0,
            "min_freq_mhz": 800.0,
            "max_freq_mhz": 3600.0,
        },
        "running_in_docker": True,
    },
    "b_cpu_per_core.jinja2": {
        "context": {
            "core_rows": [
                {"core": "#1", "bar": "▰▰▱▱▱", "usage_percent": 40.0},
                {"core": "#2", "bar": "▰▱▱▱▱", "usage_percent": 12.0},
            ]
        }
    },
    "b_cpu_times.jinja2": {
        "context": {
            "user": 10.0,
            "system": 5.0,
            "idle": 80.0,
            "iowait": 1.0,
            "irq": 0.1,
            "softirq": 0.2,
        }
    },
    "b_disk_io.jinja2": {
        "context": {
            "disks": [
                {
                    "device_name": "sda",
                    "read_bytes": "1.2 GB",
                    "read_count": 100,
                    "read_time_ms": 12,
                    "write_bytes": "3.4 GB",
                    "write_count": 200,
                    "write_time_ms": 34,
                }
            ]
        }
    },
    "b_fans.jinja2": {
        "context": {"fans": [{"sensor_name": "nct6775", "label": "fan1", "rpm": 1200}]}
    },
    "b_fs.jinja2": {
        "context": [
            {
                "device_name": "/dev/sda1",
                "fs_type": "ext4",
                "mnt_point": "/",
                "size": "100 GB",
                "used": "40 GB",
                "percent": 40.0,
                "free": "60 GB",
            }
        ],
        "running_in_docker": True,
    },
    "b_getmyid.jinja2": {
        "user_id": 101,
        "chat_id": -1001,
        "first_name": "Den <3",
        "last_name": "R&D",
        "username": "den",
        "chat_type": "Supergroup",
        "chat_title": "Ops",
        "is_bot_admin": True,
        "auto_delete_delay": 30,
    },
    "b_health_summary.jinja2": {"context": _HEALTH_CONTEXT},
    "b_how_update.jinja2": {},
    "b_index.jinja2": {"first_name": "Den"},
    "b_load_average.jinja2": {"context": [0.5, 0.6, 0.7]},
    "b_memory.jinja2": {
        "context": {
            "total": "8 GB",
            "used": "4 GB",
            "percent": 50.0,
            "free": "2 GB",
            "available": "4 GB",
            "active": "3 GB",
            "inactive": "1 GB",
            "cached": "1 GB",
            "shared": "100 MB",
        }
    },
    "b_net_connections.jinja2": {
        "context": {
            "total": 10,
            "tcp": 8,
            "udp": 2,
            "statuses": {"ESTABLISHED": 6, "LISTEN": 4},
        }
    },
    "b_net_interfaces.jinja2": {
        "context": {
            "interfaces": [
                {
                    "name": "eth0",
                    "state": "UP",
                    "speed": "1000 Mbps",
                    "mtu": 1500,
                    "ip_address": "10.0.0.2",
                }
            ]
        }
    },
    "b_net_io.jinja2": {
        "context": [
            {
                "bytes_sent": "1 GB",
                "bytes_recv": "2 GB",
                "packets_sent": 10,
                "packets_recv": 20,
                "err_out": 0,
                "err_in": 0,
                "drop_out": 0,
                "drop_in": 1,
            }
        ]
    },
    "b_notice.jinja2": {
        "title": "Bot updates",
        "message": "You are running version 0.5.0.",
        "hint": "Try again later.",
    },
    "b_plugins.jinja2": {
        "first_name": "Den",
        "plugins": {"Monitor": "InfluxDB metrics", "Outline": "VPN stats"},
    },
    "b_process.jinja2": {
        "context": {"running": 2, "sleeping": 200, "total": 202},
        "running_in_docker": True,
    },
    "b_quick_view.jinja2": {
        "context": {
            "system": {
                "uptime": "3 days",
                "load_average": [0.5, 0.6, 0.7],
                "cpu": {"cpu_percent": 12.0, "cpu_count": 4, "frequency_mhz": 2400.0},
                "memory": {"used": "4 GB", "free": "4 GB", "percent": 50.0},
                "processes": {"running": 2, "sleeping": 200, "idle": 3, "total": 205},
            },
            "docker": {"containers_count": 4, "images_count": 9},
        }
    },
    "b_sensors.jinja2": {"context": [{"sensor_name": "cpu", "sensor_value": 55.0}]},
    "b_server.jinja2": {"first_name": "Den"},
    "b_swap.jinja2": {"context": {"Total": "2 GB", "Used": "0 B", "Percent": "0%"}},
    "b_top_processes.jinja2": {
        "context": {
            "process_rows": [
                {
                    "pid": "1",
                    "name": "systemd",
                    "cpu_percent": 0.1,
                    "memory_percent": 0.2,
                }
            ],
            "running_in_docker": True,
            "timestamp": "2026-09-26 10:00:00",
        }
    },
    "b_uptime.jinja2": {"context": "3 days, 4:05:06"},
    "b_users_info.jinja2": {
        "context": {
            "users": [
                {
                    "username": "den",
                    "terminal": "pts/0",
                    "host": "10.0.0.5",
                    "started_at": "09:00",
                    "started_ago": "an hour ago",
                }
            ]
        }
    },
    "d_container_networks_info.jinja2": _container_networks_info(),
    "d_container_runtime_info.jinja2": _container_runtime_info(),
    "d_container_volumes_info.jinja2": _container_volumes_info(),
    "d_containers.jinja2": {
        **_CONTAINER_EMOJIS,
        "context": [
            {
                "name": "web",
                "id": "0123456789ab",
                "image": "nginx:1.29",
                "created": "2 weeks ago",
                "run_at": "3 hours ago",
                "status": "running",
            }
        ],
    },
    "d_containers_full_info.jinja2": _container_full_info(),
    "d_docker.jinja2": {"context": {"images_count": 9, "containers_count": 4}},
    "d_image_full_info.jinja2": {"context": {"emojis": _IMAGE_EMOJIS, "image": _IMAGE}},
    "d_image_history_info.jinja2": {
        "context": {
            "emojis": _IMAGE_EMOJIS,
            "image_name": "nginx",
            "image_id": "sha256:1a2b3c",
            "layers_count": 1,
            "layers": [
                {
                    "id": "sha256:9f8e",
                    "created": "2 weeks ago",
                    "size": "70 MB",
                    "created_by": "/bin/sh -c apt-get update",
                    "comment": "",
                }
            ],
            "hidden_layers_count": 3,
        }
    },
    "d_image_usage_info.jinja2": {
        "context": {
            "emojis": _IMAGE_EMOJIS,
            "image_name": "nginx",
            "image_id": "sha256:1a2b3c",
            "containers_count": 1,
            "running_count": 1,
            "stopped_count": 0,
            "containers": [
                {
                    "name": "web",
                    "id": "0123456789ab",
                    "status": "running",
                    "started_at": "3 hours ago",
                }
            ],
            "hidden_containers_count": 0,
        }
    },
    "d_images.jinja2": {
        "context": {
            "emojis": _IMAGE_EMOJIS,
            "images": [
                {
                    "name": "nginx",
                    "id": "sha256:1a2b3c",
                    "tags": ["nginx:1.29", "nginx:latest"],
                    "tags_count": 2,
                    "size": "187 MB",
                    "os": "linux",
                    "architecture": "amd64",
                    "variant": "N/A",
                    "created": "2 weeks ago",
                }
            ],
        }
    },
    "d_logs.jinja2": {
        "emojis": {"thought_balloon": _EMOJI},
        "logs": "[Page 1/1 | Newest first]\n2026-09-26 GET / 200\n<html> & more",
        "container_name": "web",
    },
    "d_managing_containers.jinja2": {
        "emojis": {
            "thought_balloon": _EMOJI,
            "briefcase": _EMOJI,
            "anxious_face_with_sweat": _EMOJI,
        },
        "state": "running",
        "container_name": "web",
    },
    "d_updates.jinja2": {
        "updates": {
            "nginx": {
                "current_tag": "1.29",
                "created_at_local": "2026-09-01T10:00:00Z",
                "updates": [
                    {"newer_tag": "1.30", "created_at_remote": "2026-09-20T10:00:00Z"}
                ],
            }
        },
        "no_updates": ["redis"],
    },
    "plugin_monitor_index.jinja2": {
        "first_name": "Den",
        "period_label": "Last 24 hours",
        "notice": "Period updated",
        "cpu_line": "12.0% (avg 10.0%)",
        "memory_line": "50.0% (avg 48.0%)",
        "disk_line": "40.0% (avg 40.0%)",
        "temperature_line": "55.0°C (avg 50.0°C)",
    },
    "plugin_monitor_metric.jinja2": {
        "title": "CPU usage",
        "period_label": "Last 24 hours",
        "summary_lines": ["Latest: 12.0%", "Average: 10.0%"],
        "detail_lines": ["Load average (1m): 0.50 (avg 0.40)"],
    },
    "plugin_outline_index.jinja2": {"first_name": "Den"},
    "plugin_outline_keys.jinja2": {
        "first_name": "Den",
        "context": {"accessKeys": [{"name": "phone"}, {"name": "laptop"}]},
    },
    "plugin_outline_server_info.jinja2": {
        "first_name": "Den",
        "context": {
            "name": "outline",
            "metricsEnabled": True,
            "createdTimestampMs": 1_760_000_000_000,
            "portForNewAccessKeys": 443,
        },
    },
    "plugin_outline_traffic.jinja2": {
        "first_name": "Den",
        "context": {
            "bytesTransferredByUserId": {"1": 1024},
            "userNames": {"1": "phone"},
        },
        "set_naturalsize": format_bytes,
    },
}

# Empty/degraded states that take a different template branch.
RICH_EMPTY_STATE_CASES: dict[str, dict[str, object]] = {
    "b_cpu.jinja2": {
        "context": {
            "cpu_percent": 0.0,
            "logical_cores": 1,
            "physical_cores": 1,
            "current_freq_mhz": 0,
            "min_freq_mhz": 0,
            "max_freq_mhz": 0,
        }
    },
    "b_cpu_per_core.jinja2": {"context": {"core_rows": []}},
    "b_disk_io.jinja2": {"context": {"disks": []}},
    "b_fans.jinja2": {"context": {"fans": []}},
    "b_net_connections.jinja2": {
        "context": {"total": 0, "tcp": 0, "udp": 0, "statuses": {}}
    },
    "b_net_interfaces.jinja2": {"context": {"interfaces": []}},
    "b_process.jinja2": {"context": {}},
    "b_quick_view.jinja2": {"context": {}},
    "b_sensors.jinja2": {"context": []},
    "b_swap.jinja2": {"context": {}},
    "b_top_processes.jinja2": {
        "context": {"process_rows": [], "timestamp": "2026-09-26 10:00:00"}
    },
    "b_users_info.jinja2": {"context": {"users": []}},
    "d_containers.jinja2": {**_CONTAINER_EMOJIS, "context": []},
    "d_images.jinja2": {"context": {"emojis": _IMAGE_EMOJIS, "images": []}},
    "d_updates.jinja2": {"updates": {}, "no_updates": ["redis", "postgres"]},
    "plugin_monitor_metric.jinja2": {
        "title": "Disk usage",
        "period_label": "Last hour",
        "summary_lines": [],
        "detail_lines": [],
    },
    "plugin_outline_traffic.jinja2": {
        "first_name": "Den",
        "context": {"bytesTransferredByUserId": {}, "userNames": {}},
        "set_naturalsize": format_bytes,
    },
}


def _all_rich_templates() -> list[str]:
    return sorted(
        path.name
        for path in TEMPLATES_ROOT.rglob("*.jinja2")
        if path.name not in CLASSIC_TEMPLATES
    )


class _TableAlignmentCollector(HTMLParser):
    """Collect per-row cell alignment for every table in the markup."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._row: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.tables.append([])
        elif tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._row.append(dict(attrs).get("align") or "left")

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self._row is not None:
            self.tables[-1].append(self._row)
            self._row = None


def _render(template_name: str, context: Mapping[str, object]) -> str:
    emojis = {"thought_balloon": _EMOJI}
    return Compiler.quick_render(template_name=template_name, **{**emojis, **context})


def _assert_rich_design(template_name: str, html: str) -> None:
    issues = find_rich_html_issues(html)
    assert issues == [], f"{template_name}: {issues}\n{html}"

    stripped = html.strip()
    assert stripped.startswith("<p><b>"), f"{template_name}: title must come first"
    assert not re.search(r"<h[1-6]\b", html), f"{template_name}: use <p><b> titles"
    assert not re.search(r"<li>\s*[•·\-]\s", html), f"{template_name}: double bullets"
    if "<footer>" in html:
        assert stripped.endswith("</footer>"), f"{template_name}: footer must be last"

    for table_tag in re.findall(r"<table\b[^>]*>", html):
        assert "bordered" in table_tag and "striped" in table_tag, template_name
    for table in re.split(r"<table\b", html)[1:]:
        first_row = table.split("</tr>", 1)[0]
        assert "<th" in first_row, f"{template_name}: table needs a header row"

    collector = _TableAlignmentCollector()
    collector.feed(html)
    for rows in collector.tables:
        width = len(rows[0])
        for column in range(width):
            aligns = {row[column] for row in rows if len(row) == width}
            assert len(aligns) == 1, (
                f"{template_name}: column {column} mixes alignments {aligns}"
            )


def test_every_rich_template_has_a_render_case() -> None:
    assert sorted(RICH_RENDER_CASES) == _all_rich_templates()


@pytest.mark.parametrize("template_name", sorted(RICH_RENDER_CASES))
def test_rich_template_renders_valid_design(template_name: str) -> None:
    html = _render(template_name, RICH_RENDER_CASES[template_name])
    _assert_rich_design(template_name, html)


@pytest.mark.parametrize("template_name", sorted(RICH_EMPTY_STATE_CASES))
def test_rich_template_empty_states_render_valid_design(template_name: str) -> None:
    html = _render(template_name, RICH_EMPTY_STATE_CASES[template_name])
    _assert_rich_design(template_name, html)


def test_rich_templates_escape_dynamic_values() -> None:
    getmyid = _render("b_getmyid.jinja2", RICH_RENDER_CASES["b_getmyid.jinja2"])
    assert "Den &lt;3" in getmyid
    assert "R&amp;D" in getmyid

    logs = _render("d_logs.jinja2", RICH_RENDER_CASES["d_logs.jinja2"])
    assert "&lt;html&gt; &amp; more" in logs
