# Changelog

All notable changes are documented in this file.

## [0.3.0] - 2026-02-17

### Added

- Health monitoring subsystem with component-level checks and startup health reporting.
- Configuration versioning with automatic migration (`config_version` handling).
- Paginated Docker UI flows (containers/images/logs), including log export to file.
- Secure message deletion manager with scheduled cleanup flow.
- `/getmyid` command and stronger access-control middleware behavior.
- CLI support for log format selection (`--log-format human|json`).

### Changed

- Docker and psutil pipelines optimized: reduced duplicate checks and fewer expensive roundtrips.
- Logging pipeline redesigned: normalized event names, context deduplication, trace IDs, safer masking.
- Runtime/build toolchain modernized (Python 3.13 alignment, pyproject workflow, CI/CD updates, tini-based container
  startup).
- Container details/handlers flow reworked with improved pagination context and callback behavior.
- Installer workflow refactored and documented for safer defaults.
- Docker counters cache switched from permanent `lru_cache` to TTL-based targeted invalidation.
- `quick_view` metric collection simplified to reduce threadpool overhead on hot path.
- Rate-limit request buffer moved to `deque` for O(1) cleanup.

### Fixed

- Telegram `MESSAGE_TOO_LONG` failures during log rendering.
- 2FA flow now accepts plain code input, with proper input cleanup outside auth flow.
- False `degraded` health status due to expired sessions in health stats.
- Entrypoint health check behavior made deterministic and fail-fast.
- Docker image update detection edge cases (same tag/new build ambiguity).
- Polling conflict/restart edge cases and startup/shutdown stability issues.
- Multiple ruff/mypy typing and lint regressions across core modules.
- Bot update version check now uses semantic version comparison instead of lexical string compare.
- Docker Hub tag fetch flow cleaned up for namespaced repositories and duplicate 404 log noise.
- Logging payload consistency improved by removing nested `extra={...}` records.

### Security

- Hardened callback/container authorization checks and reduced auth bypass surface.
- Added container name validation to mitigate injection vectors.
- Improved log/file delivery safeguards and masking correctness.
- Webhook IP verification hardened: trusted proxy allowlist with strict forwarded-header handling.
- Uvicorn wildcard forwarded headers trust removed (`proxy_headers=False` by default in webhook mode).
- Webhook and Telegram IP caches are now bounded to mitigate memory growth under hostile traffic.
- Webhook error logging now keeps only minimal update metadata (`update_id`/`update_type`) instead of full payload.
- Installer hardening:
    - safer install-dir validation,
    - package-manager Docker/Compose installation by default,
    - unverified `get.docker.com` fallback moved to explicit opt-in.

### Documentation

- Installation, Docker, settings, CLI args, plugins, and debug docs synchronized with actual runtime behavior.
- Installer security model and new operational constraints explicitly documented.
- Added `webhook_config.trusted_proxy_ips` to sample config with secure defaults and usage notes.

[0.3.0]: https://github.com/orenlab/pytmbot/compare/0.2.2...06a30a6
