# Changelog

## [0.3.1] — 20260406

Patch release focused on dependency refresh, structural cleanup, and release polish.

### Security And Reliability

- Refreshed runtime and development dependencies, including security-driven updates, and regenerated `uv.lock`.
- Tightened callback, Docker, logging, and runtime guard paths; improved several reliability edge cases surfaced by CI
  and static analysis.

### Quality And Maintainability

- Reduced structural duplication across core handlers, Docker update flows, utilities, and tests.
- Raised the default `codeclone` grade to `B` and expanded regression coverage around the refactors.

### Release And Docs

- Bumped the project, sample config, docs, and Docker exact-tag references to `0.3.1`.
- Updated Docker Hub and release-facing documentation to match the supported stable-image contract.

## [0.3.0] — 20260323

Major release focused on observability, Docker UX, security hardening, and release discipline.

### User-Facing

- Added health monitoring with startup/component checks and a clearer health summary.
- Expanded server views: CPU, network, disk, users, fans, sensors, and refreshed quick-view pages.
- Improved Docker UX with pagination for containers/images/logs, log export, and protected `Volumes` / `Networks` views.
- Added secure message deletion, `/getmyid`, duplicate-update protection, config versioning with automatic migration,
  and `human` / `json` log format selection.
- Refined navigation, templates, quick views, formatting, and general Telegram UX copy.

### Security And Reliability

- Hardened callback/container authorization, TOTP flows, log/file delivery, and runtime masking.
- Added webhook trusted-proxy/IP validation, bounded IP caches, reduced webhook error logging, and cleaner polling
  fallback.
- Removed raw InfluxDB URL/org/bucket values from runtime logs and exception metadata.
- Improved Telegram error handling for `400`, `429`, and long messages; fixed degraded health false positives and
  entrypoint health behavior.
- Fixed Docker log-driver fallback, semantic version comparison for updates, and multiple cache/performance regressions
  in Docker, psutil, and monitoring paths.

### Platform And Release Engineering

- Raised the runtime baseline to Python 3.12 and modernized the toolchain around `uv`, Buildx, and current Ubuntu
  images.
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
