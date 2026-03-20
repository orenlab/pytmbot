# Changelog

All notable changes are documented in this file.

## [0.3.0] — Unreleased

### Added

- GitHub Actions CI with Python 3.12–3.14 matrix and `codeclone` checks.
- Health monitoring subsystem with component-level checks and startup reporting.
- Extended server views: CPU, network, disk, users, fans, and quick-view pages with live refresh.
- Docker UI pagination (containers/images/logs) with log export.
- 2FA-protected container views (`Volumes`, `Networks`).
- Secure message deletion scheduler.
- `/getmyid` command and stronger access control.
- CLI option for log format (`human|json`).
- `UpdateDedup` middleware for duplicate update protection.
- Regression tests for Outline plugin.
- Configuration versioning with automatic migration.

### Changed

- Refined UI navigation and simplified health screen layout.
- Updated templates and quick-views for new server/Docker capabilities.
- Unified size formatting (`humanize`) and ID masking scheme.
- Minimum runtime Python version set to 3.12.
- Optimized Docker/psutil and logging pipelines; added trace IDs, safer masking.
- Modernized build toolchain (Python 3.13, `uv`, `tini`, Ubuntu images, Buildx v0.24).
- Caching reworked: TTL for Docker counters, O(1) rate-limit buffer cleanup.
- Simplified `quick_view` metrics flow.
- Migrated Outline plugin to `pyoutlineapi 0.4.0`.
- Reduced memory usage with `__slots__`; strict typing via `mypy --strict`.

### Fixed

- Graceful fallback for unsupported Docker log drivers.
- Tests now use `pytmbot.yaml.sample` instead of a real config.
- Closed multiple race, performance, and security issues (webhook, middleware, Docker, monitoring).
- Fixed CPU/IO/memory regressions and cache conflicts.
- Telegram errors (`400`, `MESSAGE_TOO_LONG`, `429`) handled cleanly.
- 2FA input cleanup; restored post-deletion navigation UI.
- Fixed false `degraded` health status and deterministic entrypoint health checks.
- Corrected Python path in container entrypoint.
- Switched update comparison to semantic versioning.
- Cleaned Docker Hub tag resolution and webhook failover (polling fallback, better masking/logging).
- Expanded and fixed InfluxDB dashboard template.

### Removed

- Experimental `Services` handler and callbacks.
- Legacy `tools/install.sh` installer (Docker-only install flow now used).

### Security

- Strengthened callback/container authorization and input validation.
- Improved log/file delivery safeguards and data masking.
- Webhook IP verification with trusted-proxy allowlist.
- Removed wildcard proxy header trust, bounded IP caches.
- Minimized webhook error logs (only `update_id` and `update_type` retained).

### Documentation

- Updated installation, Docker, CLI, plugin, and debug documentation.
- Added unified docs index (`docs/README.md`).
- Deprecated legacy script installer docs.
- Added `trusted_proxy_ips` config and webhook failover details.
- Docs now reflect current runtime, TLS, and security behavior.
