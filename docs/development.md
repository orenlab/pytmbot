# Development And Quality Gates

This document describes the current local development workflow.

Source of truth:

- `pyproject.toml`
- `.pre-commit-config.yaml`
- `.github/workflows/`

## Local Setup

Install dependencies with `uv`:

```bash
uv sync --all-extras --dev
```

For tests and local runs, the repository sample config can be used:

```bash
export PYTMBOT_CONFIG_PATH=pytmbot.yaml.sample
```

## Common Commands

Run the test suite:

```bash
uv run pytest
```

Run formatting and linting:

```bash
uv run ruff format .
uv run ruff check .
```

Run type checking:

```bash
uv run mypy .
```

Run structural quality checks:

```bash
uv run codeclone .
```

Build documentation strictly:

```bash
uv run zensical build --strict
```

Preview documentation locally:

```bash
uv run zensical serve
```

Run the full local gate set:

```bash
uv run pre-commit run --all-files
```

## Quality Gates In This Repository

Current local / CI gates include:

- Ruff format
- Ruff lint
- mypy with `strict = true`
- pytest with coverage
- codeclone
- pre-commit hooks
- `uv sync --frozen` in CI to enforce `uv.lock`

## CI Overview

Current GitHub Actions workflows cover:

- Python tests on `3.12`, `3.13`, `3.14`
- Ruff
- mypy
- codeclone baseline checks on Python `3.14`
- Zensical strict build for the docs site
- Docker image builds for development, releases, and weekly stable-line rebuilds
- GitHub Pages deployment from the GitHub Actions artifact flow

## Release Image Policy

Starting with the `0.3.0` release line:

- all versions older than `0.3.0` are end-of-life
- the `0.3.x` line is end-of-life as of `0.4.0`
- the `0.4.x` line is end-of-life as of `0.5.0`
- only the current `0.5` stable line receives weekly rebuilds
- exact release tags stay immutable
- floating stable tags are refreshed by the weekly rebuild workflow
- development tags are separate from the public stable contract

See [release_policy.md](release_policy.md) for the published tag semantics.

## Documentation Site Deployment

Current publication model:

- docs are built on pushes and pull requests that touch docs-related files
- the public Pages deploy runs only on `push` to the repository default branch
- in this repository the current default branch is `master`

Operational notes:

- the repository Pages source must be set to `GitHub Actions`
- a green `Docs` workflow on a feature branch validates the build, but does not publish the site
- if you want a custom domain later, add a repository-root `CNAME` file with the final domain; the workflow will copy it into the built site
- HTTPS for a custom domain is enabled in GitHub Pages settings after DNS is configured correctly

## Documentation Maintenance Rules

- `pytmbot.yaml.sample` is the canonical sample config.
- User-facing files outside `docs/` (`README.md`, `SECURITY.md`, Docker Hub README, bot templates) must link to `https://orenlab.github.io/pytmbot/`, not repository `docs/*.md` paths.
- Docs should point to current code paths, not historical behavior.
- Docs site must pass `zensical build --strict`.
- If codeclone flags dynamic false positives, use the supported inline suppression syntax rather than broad ignores.

Current suppression form:

```python
# codeclone: ignore[dead-code]
```

## Rich Message Templates

Structured screens are sent as Telegram Rich Messages (`InputRichMessage(html=...)`) through the helpers in
`pytmbot/handlers/handlers_util/rich_messages.py`. Rich templates follow one layout contract, enforced by
`tests/test_rich_templates_markup.py`:

- the first block is a bold paragraph title: `<p><b>{emoji} Title</b></p>`; section titles use the same form (no
  `<h1>`–`<h6>` headings)
- tabular data uses `<table bordered striped compact>` (compact cell padding, Bot API 10.3) with a header row;
  every header cell sets `align` explicitly (Telegram centers headers by default), and a column is either left- or
  right-aligned in every row
- lists use `<ul>`/`<ol>` without manual bullets; hints and warnings are `<p><i>…</i></p>` paragraphs
- metadata such as pagination, timestamps, or auto-delete notices goes into a single `<footer>` placed last
- table cells and paragraphs contain inline formatting only; line breaks come from separate blocks, not `\n`
- dynamic values are escaped with `|e`

Delivery safeguards:

- `build_rich_html_message()` wraps plain text into paragraphs and trims content that exceeds Telegram rich-message
  limits (32,768 characters, 500 blocks, 16 nesting levels, 20 table columns) at a row/item/block boundary
- `send_rich_bot_message()` falls back to a classic plain-text message when Telegram rejects the rich payload
- `edit_callback_message_text()` keeps rich messages rich: classic text aimed at a rich message is converted to rich
  paragraphs instead of overlaying it
- a test fixture validates every `InputRichMessage` built during the test run with `find_rich_html_issues()`

Short conversational replies and the 2FA prompts (`b_back`, `b_echo`, `b_none`, `a_*` templates) intentionally stay
classic messages.

## Adding Or Changing Features

When changing behavior, update together:

- implementation
- tests
- `README.md` if user-facing behavior changes
- relevant files in `docs/`
- `CHANGELOG.md` when the change is release-notable
