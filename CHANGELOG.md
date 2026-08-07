# Changelog

## [0.5.0] — Unreleased

### Added

- Telegram Rich Messages helpers (`send_rich_*` / `InputRichMessage(html=...)`) for structured screens, with the same dual-markup nav-keyboard sync used by classic sends.
- `KeyboardButton.style` on reply menus: `primary` for Server/Docker/Quick view/Health, `danger` for Back to main menu.

### Changed

- Migrated structured server, Docker list/detail, plugin monitor/outline, and start/about/plugins screens from classic HTML/Markdown to rich HTML templates.
- Rich metric layouts use compact `<p><b>…</b></p>` titles (not large `<h2>`/`<h3>` headings) with native rich tables (`<table bordered striped>`, `<th>`/`<td>`, optional `align`) for structured metrics.
- Migrated Network I/O / interfaces / connections (plus Disk I/O, fans, and users overlays) from ASCII/`<pre>` classic HTML to the same compact rich format.
- Bumped runtime dependencies including `pyTelegramBotAPI` (`>=4.36.0`) for current Bot API keyboard and rich-message types.
- Bumped Docker build base images: Ubuntu `26.04` and `ghcr.io/astral-sh/uv:0.12.2`.
- Raised the development app/`config_version` line to `0.5.0-dev`.

### Fixed

- Restored reply-keyboard navigation after Quick view and other inline screens by re-attaching the section menu when both an inline keyboard and a navigation keyboard are required (notably on iOS).
- Fixed rich-message overlay when editing Memory → Swap (and CPU → Process overview) by keeping the same message lifecycle on `rich_message` edits instead of mixing classic `text` edits onto rich content.
- Stopped forwarding classic-only kwargs such as `link_preview_options` into `TeleBot.send_rich_message` (broke `/start` and `/about`).
- Fixed empty/blank rows in Docker container detail rich tables by keeping emoji badges outside table cells and omitting empty/`N/A` finished rows.
## [0.4.0] — 20260624

Modest stable release focused on Telegram iOS keyboard reliability, unified outbound messaging, dependency maintenance, and documentation polish.

### Fixed

- Fixed the reply keyboard disappearing on Telegram iOS during normal bot use by enabling persistent section keyboards and re-attaching the correct navigation keyboard on text-only replies, middleware warnings, and post-delete navigation.

### Security

- Bumped `pydantic-settings` to `>=2.14.2` and refreshed transitive dependencies in `uv.lock` to address symlink traversal in `NestedSecretsSettingsSource`.

### Changed

- Added `0.4.0` to the supported `config_version` compatibility matrix.
- Unified Telegram outbound messaging through `send_bot_message()` / `send_*_message()` helpers so text-only replies, plugin screens, auth flows, and post-delete navigation consistently preserve the active reply keyboard.
- Post-delete navigation now accepts a section keyboard (`main`, `server`, or `docker`); Docker log exports restore the Docker menu after auto-delete.
- Refreshed direct dependencies and regenerated `uv.lock`: `fastapi` (`>=0.138.0`), `pydantic-settings` (`>=2.14.2`), `pyotp` (`>=2.10.0`), and dev `pytest` (`>=9.1.1`).
- Updated release metadata, sample configuration, documentation, Docker tag references, and user-facing documentation links to `0.4.0`.

## [0.3.3] — 20260612

Patch release focused exclusively on dependency maintenance.

### Maintenance

- Refreshed runtime and development dependencies and regenerated `uv.lock`.
- Updated release metadata, sample configuration, documentation, and exact Docker tag references to `0.3.3`.
- No intentional feature or behavior changes.

## [0.3.2] — 20260516

Patch release focused on dependency refresh, Docker polish, and release documentation.

### Security And Reliability

- Refreshed runtime and development dependencies and regenerated `uv.lock`.
- Updated Docker runtime configuration and image metadata for the current supported patch line.

### Docs And Release

- Bumped project docs, sample config, security policy, and exact Docker tag references to `0.3.2`.
- Migrated the documentation site from MkDocs Material to Zensical with strict CI validation.
- Kept the `0.3` stable-line contract unchanged for floating weekly rebuilds.

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
