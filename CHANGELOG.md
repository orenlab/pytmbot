# Changelog

## [0.5.0] — 20260926

Feature release that moves structured bot screens to Telegram Rich Messages, adds colored keyboard accents, and
refreshes dependencies, Docker build images, and CI.

### Added

- Telegram Rich Messages (Bot API 10.1+) for structured screens: server metrics, Quick view, Health, Uptime, Server and
  Docker menus, Docker lists and details, container actions, image and bot update checks, `/getmyid`,
  start/about/plugins, and the Monitor and Outline plugin screens.
- Rich message safeguards: content is trimmed to Telegram rich-message limits (32,768 characters, 500 blocks,
  16 nesting levels, 20 table columns) at a row or block boundary, and a rejected rich payload falls back to a
  plain-text message instead of failing the handler.
- `KeyboardButton.style` accents on reply menus (`primary` for Server/Docker/Quick view/Health, `danger` for Back to
  main menu) and inline button styles for container actions (`danger` Stop, `primary` Restart, `success` Start).
- The bot update check shows GitHub release notes in a collapsible block.

### Changed

- Unified rich layout: bold paragraph titles, bordered striped tables with header rows and consistent column
  alignment, and footers for pagination, timestamps, and auto-delete notices. A template render test and a validator
  applied to every rich message built in tests keep the layout consistent.
- Network I/O, interfaces, connections, Disk I/O, fans, and users views moved from ASCII/preformatted text to native
  tables.
- Docker list pagination and image detail sizing follow rich-message limits instead of the classic 4,096-character
  budget.
- `/getmyid` now states that the message is deleted automatically instead of suggesting to save it.
- Bumped runtime dependencies, including `pyTelegramBotAPI` 4.37.0 (Bot API 10.3), `uvicorn`, `pydantic`, `emoji`,
  `cachetools`, and `click`, and regenerated `uv.lock`.
- Bumped Docker build images (Ubuntu `26.04`, `ghcr.io/astral-sh/uv:0.12.19`), the BuildKit driver image (`v0.33.0`),
  and every pinned GitHub Action to its latest release.
- Refreshed development tooling (`ruff`, `mypy`, `zensical`, `pre-commit`, typing stubs); `codeclone` stays on the
  stable 2.0.x release so the committed baseline remains trusted in CI.
- Added `0.5.0` to the supported `config_version` compatibility matrix and moved the supported stable image line to
  `0.5`; updated release metadata, sample configuration, documentation, and Docker Hub README.

### Fixed

- Restored reply-keyboard navigation after Quick view and other inline screens by re-attaching the section menu when
  both an inline keyboard and a navigation keyboard are required (notably on iOS).
- The image update check no longer replaces the rich images list with a legacy Markdown message; container restart
  results and the update guide keep the rich message lifecycle as well.
- Fixed rich-message overlay when editing Memory → Swap (and CPU → Process overview) by keeping the same message
  lifecycle on rich edits instead of mixing classic text edits onto rich content.
- The container actions screen no longer renders as a single run-on paragraph or mentions an unavailable Remove action.
- Removed duplicated bullets in Monitor plugin lists.
- Stopped forwarding classic-only kwargs such as `link_preview_options` into `TeleBot.send_rich_message` (broke
  `/start` and `/about`).
- Fixed empty/blank rows in Docker container detail tables by keeping emoji badges outside table cells and omitting
  empty/`N/A` finished rows.

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
