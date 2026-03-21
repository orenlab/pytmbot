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
uv run mkdocs build --strict
```

Preview documentation locally:

```bash
uv run mkdocs serve
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
- blocking Hadolint checks for Dockerfile changes on pushes and pull requests

## CI Overview

Current GitHub Actions workflows cover:

- Python tests on `3.12`, `3.13`, `3.14`
- Ruff
- mypy
- codeclone baseline checks on Python `3.14`
- MkDocs strict build for the docs site
- Docker image builds for development, releases, and weekly stable-line rebuilds
- Hadolint for the Dockerfile
- GitHub Pages deployment from the GitHub Actions artifact flow

## Release Image Policy

Starting with the `0.3.0` release line:

- all versions older than `0.3.0` are end-of-life
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
- Docs should point to current code paths, not historical behavior.
- Docs site must pass `mkdocs build --strict`.
- If codeclone flags dynamic false positives, use the supported inline suppression syntax rather than broad ignores.

Current suppression form:

```python
# noqa: codeclone[dead-code]
```

## Adding Or Changing Features

When changing behavior, update together:

- implementation
- tests
- `README.md` if user-facing behavior changes
- relevant files in `docs/`
- `CHANGELOG.md` when the change is release-notable
