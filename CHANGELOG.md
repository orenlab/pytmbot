# Changelog

## [0.5.1] — 20261019

Patch release focused on Docker hardening and dependency maintenance.

### Security

- Container actions could reach a different container: buttons carried a lowercased name, and Docker falls back to
  ID-prefix lookup. Buttons now carry the short container ID, and every read and action verifies that Docker resolved
  exactly the container that was shown.
- Container and image details no longer reveal secrets: environment variables are shown as keys only, and passwords
  in URLs and secret-looking command-line values are masked.
- Image update checks query Docker Hub only for Docker Hub images; images from other registries are no longer matched
  against look-alike Docker Hub repositories.
- In group chats, another user can no longer delete your Docker messages or trigger your pending action through 2FA.

### Fixed

- A hung or unreachable Docker daemon no longer blocks the bot: after one timeout, calls fail fast and reconnect
  automatically.
- Image update checks run in the background with a 60-second limit; failed checks are listed separately instead of as
  "Up to date", and version suggestions stay within the same tag family.
- Container lists no longer fail when a container or image disappears mid-listing; statuses are fresh right after an
  action; CPU usage is calculated correctly.
- New container and image alerts in the Monitor plugin are no longer lost when the notification budget is exhausted.
- Long and mixed-case container names work on all buttons.
- 2FA lockouts last the full 10 minutes, pending codes are no longer dropped by the session cleanup, admins without a
  Telegram username can use 2FA, and the post-2FA "Return" button no longer repeats Stop or Restart.

### Changed

- Stop and Restart ask for confirmation, and a second press while an action is running is refused.
- Docker image: the `# syntax` directive is now honoured, and no file in the image is writable by the `root` group or
  by everyone, so the image user's compatibility groups only matter for the Docker socket.
- Startup and `--check-docker` log the Docker socket's group ID and the exact `--group-add` value when access is
  missing, instead of attempting to change groups.
- Documentation: Docker socket access (`group_add` with an optional `DOCKER_GID`, least-privilege
  `--user 1001:1001`, a tested socket-proxy setup that allows only the API calls the bot uses), and a correction:
  a `:ro` socket mount does not restrict the Docker API.
- Bumped dependencies (incl. `pyTelegramBotAPI` 4.37.1, `pydantic` 2.14, `fastapi` 0.146, `aiohttp` 3.14.5), uv
  `0.13.1`, BuildKit `v0.34.0`, and `astral-sh/setup-uv` v10.3.0.
- New optional `docker` settings: `timeout` (clamped to 5-300 s), and `cert_path`, `key_path`, `ca_cert`,
  `verify_hostname` for a remote `https://` daemon.

## [0.5.0] — 20260926

Feature release: structured bot screens move to Telegram Rich Messages; dependencies, Docker images, and CI are
refreshed.

### Added

- Telegram Rich Messages (Bot API 10.1+) with native tables for all structured screens: server metrics, Quick view,
  Health, menus, Docker lists and details, container actions, update checks, `/getmyid`, and plugin screens.
- Rich message safeguards: content is trimmed to Telegram limits, and a rejected rich payload falls back to plain text.
- Colored buttons: accents on reply menus and color-coded container actions (Stop, Restart, Start); back navigation
  sits on its own full-width row, and inline back buttons use short labels so they fit on phones.
- `/about` command, a bot short description, and a friendly hint for unrecognized messages in private chats.

### Changed

- One consistent screen layout (bold titles with section icons, compact bordered tables with aligned header rows,
  "updated at" footers, empty states), covered by render tests.
- Refreshed menu labels and icons (`About`, `Processes`, `Get 2FA QR code`; the old labels still work), command
  descriptions, and user-facing copy for menus, 2FA, errors, and update notices; release notes are rendered as
  formatted text.
- Reply buttons are matched by their exact label (the leading emoji is optional) instead of by substring, so any
  text containing `CPU` no longer opens the CPU screen. Plugins should register buttons with `reply_button_pattern()`.
- Bumped dependencies (incl. `pyTelegramBotAPI` 4.37.0 / Bot API 10.3), Docker build images (Ubuntu `26.04`,
  uv `0.12.19`), BuildKit, and all pinned GitHub Actions.
- Added `0.5.0` to the `config_version` compatibility matrix; `0.5` is now the supported stable image line.

### Fixed

- Reply keyboard disappearing after Quick view and other inline screens (notably on iOS); a single
  "Use the menu below to continue." follow-up per chat restores it.
- Inline buttons spinning until timeout when a handler did not answer the callback; every press is now acknowledged.
- Container actions screen advertising a Remove action that does not exist.
- Monitor plugin alerts escape container, image, process, sensor, and mount point names, so an unusual name no
  longer makes Telegram reject the alert.

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
