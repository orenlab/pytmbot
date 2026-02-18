# pyTMBot Roadmap

## Current Focus (0.3.x line)

- Runtime hardening for Docker deployment
- Documentation and install-flow consistency
- Regression coverage for auth/session/docker/webhook flows
- Stable release of `0.3.0`

## Near-Term Priorities

### P0

- Complete `0.3.0` release cut (image tags + docs + config compatibility)
- Keep mypy/ruff/pre-commit/codeclone gates green in CI
- Maintain webhook security baseline (`trusted_proxy_ips`, secret token, rate-limit controls)

### P1

- Improve local installer path to match uv-based dependency management
- Expand integration tests for Docker-heavy flows (large image/container sets)
- Continue log signal-to-noise tuning without losing incident visibility

### P2

- Additional plugin capabilities and operational telemetry
- Optional architecture improvements (including async opportunities where justified)

## Status Snapshot

| Area | Status |
|---|---|
| Docker runtime hardening | In progress |
| Test coverage expansion | In progress |
| Logging refactor and cleanup | In progress |
| Release readiness (`0.3.0`) | In progress |

## Notes

- Roadmap items are directional and may be reprioritized based on production findings.
- For implemented behavior, code and tests are the source of truth.
