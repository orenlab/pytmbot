# Roadmap

This document tracks planned work. It is not the source of truth for implemented behavior.

Implemented behavior is defined by:

- `pytmbot/`
- `tests/`
- `pytmbot.yaml.sample`

## Current Line

Active release line:

- `0.3.x`

Primary objective:

- stabilize and complete the `0.3.3` release line

## Active Priorities

### Release Readiness

- keep Docker image, docs, and config schema aligned
- keep release tags and published images consistent
- preserve backward-compatible config migration for supported configs

### Runtime Hardening

- maintain webhook security controls
- keep Docker degraded-mode vs strict-mode behavior predictable
- continue reducing noisy failures without hiding operational errors

### Test And Quality Coverage

- keep `ruff`, `mypy`, `pytest`, `pre-commit`, and `codeclone` green
- expand regression coverage for Docker-heavy flows
- expand coverage for auth, session, and webhook edge cases

### Documentation Maintenance

- keep user-facing docs aligned with actual handlers, middleware, and config
- keep command and deployment docs aligned with current runtime

## Backlog

### Near Term

- more integration coverage for large container/image sets
- more release validation around config migrations and startup diagnostics
- further cleanup of logging signal-to-noise

### Medium Term

- incremental plugin capabilities where they fit the current architecture
- operational telemetry improvements
- architecture changes only when they solve a measured problem

## Non-Goals For This Line

- reintroducing a non-Docker installation path
- broad architectural rewrites without production justification
- undocumented feature growth that bypasses tests and docs

## Notes

- Roadmap items may be reprioritized.
- The roadmap does not guarantee delivery dates.
