# Changelog

All notable changes are documented in this file.

## [0.3.0] - Unreleased

### Added

- GitHub Actions workflow `tests.yml` with test matrix for Python 3.12, 3.13, and 3.14, plus codeclone baseline check in
  CI.
- Server health summary flow in UI with refresh callback and richer operational snapshot.
- Extended server inline views: CPU overview/per-core/times, network interfaces/connections, disk I/O, active users,
  fan speeds, and quick-view drill-down pages.
- Health monitoring subsystem with component-level checks and startup health reporting.
- Configuration versioning with automatic migration (`config_version` handling).
- Paginated Docker UI flows (containers/images/logs), including log export to file.
- 2FA-protected inline container runtime views for `Volumes` and `Networks` with dedicated callbacks/templates.
- Secure message deletion manager with scheduled cleanup flow.
- `/getmyid` command and stronger access-control middleware behavior.
- CLI support for log format selection (`--log-format human|json`).
- Dedicated regression tests for installer and Outline plugin flows.

### Changed

- Quick-view navigation refined (clearer actions on current screen, less redundant controls).
- Health screen wording and layout simplified for better readability; load section formatting clarified.
- `b_how_update.jinja2` migrated to Docker Compose update example; `b_index.jinja2` updated to reflect new server
  capabilities.
- Size formatting normalized to `humanize`-based output across updated server/docker views.
- User/chat ID masking unified across logs to one consistent format (first 2 and last 2 digits visible for 10-digit
  IDs).
- Runtime minimum Python version aligned to 3.12 for launcher validation and packaging constraints.
- Docker and psutil pipelines optimized: reduced duplicate checks and fewer expensive roundtrips.
- Logging pipeline redesigned: normalized event names, context deduplication, trace IDs, safer masking.
- Runtime/build toolchain modernized (Python 3.13 alignment, uv-based dependency workflow, CI/CD updates, tini-based
  container startup).
- Container image stack migrated to Ubuntu-based multi-stage builds with smaller runtime footprint and clearer layer
  separation.
- Release/dev image pipelines standardized to Buildx v0.24 cache flow (`gha` cache), SBOM/provenance and explicit
  bytecode policy (`COMPILE_BYTECODE`).
- Supported scheduled tag-rebuild scope narrowed to `0.3.0`, with tag-existence precheck to keep CI green before
  release tag publication.
- Container details/handlers flow reworked with improved pagination context and callback behavior.
- Installer workflow refactored and documented for safer defaults.
- Installer now supports explicit non-interactive/test-mode execution for CI and scripted runs.
- Local installer dependency setup switched to `pip` with `pip3` fallback in virtualenv (no host `uv` bootstrap).
- Docker counters cache switched from permanent `lru_cache` to TTL-based targeted invalidation.
- `quick_view` metric collection simplified to reduce threadpool overhead on hot path.
- Rate-limit request buffer moved to `deque` for O(1) cleanup.
- Outline plugin migrated to `pyoutlineapi` `0.4.0` with updated client integration flow.
- Selected high-churn runtime classes moved to `__slots__` to reduce per-instance memory overhead.

### Fixed

- Tests no longer require a real `pytmbot.yaml`: pytest now uses `pytmbot.yaml.sample` via `PYTMBOT_CONFIG_PATH` in
  test bootstrap/CI.
- Closed pre-release hardening gaps across security/resilience/performance batches (webhook flow, middleware races,
  Docker adapter behavior, monitoring/polling restart paths, and Influx sanitization/retry flows).
- Resolved CPU/IO/memory hot-path regressions from recent changes (reduced blocking operations and cache conflicts).
- Telegram `400 message is not modified` is now treated as no-op for all new server inline handlers added today
  (`system_views`, `swap`, `top_process`) via a shared helper and test coverage.
- Telegram `MESSAGE_TOO_LONG` failures during log rendering.
- 2FA flow now accepts plain code input, with proper input cleanup outside auth flow.
- Sensitive auto-deletion flows now keep UI navigation: after bot-driven deletion, users receive a `Back to main menu`
  keyboard prompt.
- False `degraded` health status due to expired sessions in health stats.
- Entrypoint health check behavior made deterministic and fail-fast.
- Entrypoint Python interpreter path fixed to use `/opt/venv/bin/python3`, resolving missing-package edge cases in
  container run configs.
- Docker image update detection edge cases (same tag/new build ambiguity).
- Polling conflict/restart edge cases and startup/shutdown stability issues.
- Multiple ruff/mypy typing and lint regressions across core modules.
- Bot update version check now uses semantic version comparison instead of lexical string compare.
- Docker Hub tag fetch flow cleaned up for namespaced repositories and duplicate 404 log noise.
- Logging payload consistency improved by removing nested `extra={...}` records.

### Removed

- Removed experimental `Services` server handler, callbacks, and related UI button wiring.

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
    - unverified `get.docker.com` fallback moved to explicit opt-in,
    - mandatory startup SHA256 integrity gate with explicit `YES` confirmation against published hash.

### Documentation

- Installation, Docker, settings, CLI args, plugins, and debug docs synchronized with actual runtime behavior.
- Installer security model and new operational constraints explicitly documented.
- `docs/script_install.md` now includes a secure hash-verification flow and expected installer SHA256 for `master`.
- Updated `docs/script_install.md` with the latest `tools/install.sh` SHA256 value after installer updates.
- Added `webhook_config.trusted_proxy_ips` to sample config with secure defaults and usage notes.

[0.3.0]: https://github.com/orenlab/pytmbot/compare/0.2.2...06bb1db
