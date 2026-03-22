# Changelog

## [0.3.0] — Unreleased

Major release focused on observability, Docker UX, security hardening, and release discipline.

### User-Facing

- Added health monitoring with startup/component checks and a clearer health summary.
- Expanded server views: CPU, network, disk, users, fans, sensors, and refreshed quick-view pages.
- Improved Docker UX with pagination for containers/images/logs, log export, and protected `Volumes` / `Networks` views.
- Added secure message deletion, `/getmyid`, duplicate-update protection, config versioning with automatic migration, and `human` / `json` log format selection.
- Refined navigation, templates, quick views, formatting, and general Telegram UX copy.

### Security And Reliability

- Hardened callback/container authorization, TOTP flows, log/file delivery, and runtime masking.
- Added webhook trusted-proxy/IP validation, bounded IP caches, reduced webhook error logging, and cleaner polling fallback.
- Removed raw InfluxDB URL/org/bucket values from runtime logs and exception metadata.
- Improved Telegram error handling for `400`, `429`, and long messages; fixed degraded health false positives and entrypoint health behavior.
- Fixed Docker log-driver fallback, semantic version comparison for updates, and multiple cache/performance regressions in Docker, psutil, and monitoring paths.

### Platform And Release Engineering

- Raised the runtime baseline to Python 3.12 and modernized the toolchain around `uv`, Buildx, and current Ubuntu images.
- Added CI coverage for Python 3.12–3.14, `codeclone`, frozen `uv.lock` installs, and stricter packaging/docs checks.
- Pinned critical GitHub Actions workflows to immutable commit SHAs.
- Standardized public image tags: immutable `0.3.0`, floating `0.3`, `stable`, and `latest`.
- Weekly Docker rebuilds now refresh only the supported stable line and never republish exact release tags.

### Plugins And Docs

- Migrated the Outline plugin to `pyoutlineapi 0.4.0` and expanded plugin regression coverage.
- Expanded and fixed the InfluxDB dashboard template.
- Updated installation, Docker, CLI, plugin, security, and debug docs; added a release/image-tag policy document.

### Removed

- Experimental `Services` handler/callbacks.
- Legacy `tools/install.sh` installer in favor of the Docker-first install flow.
