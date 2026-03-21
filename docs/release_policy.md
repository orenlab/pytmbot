# Release And Image Tag Policy

This document defines the supported release and Docker image contract starting with the `0.3.0` release line.

Source of truth:

- `.github/workflows/release-to-docker-ci.yml`
- `.github/workflows/rebuild_supported_tags.yml`
- `.github/workflows/development_image_ci.yml`
- `Dockerfile`

## Support Scope

- Starting with `0.3.0`, all versions older than `0.3.0` are end-of-life.
- Only the current `0.3` stable line receives rebuilds and security refreshes.
- No compatibility or support guarantees are provided for pre-`0.3.0` images.

## Public Stable Tags

Public stable tags published to `orenlab/pytmbot`:

- `0.3.0`: exact release image, immutable
- `0.3`: current supported stable line, mutable
- `stable`: alias for the current supported stable line, mutable
- `latest`: alias for `stable`, mutable
- `0.3-rYYYYMMDD`: dated stable-line rebuild, mutable only by date creation

## Tag Semantics

- Use `0.3.0` when you need a reproducible artifact tied to a specific release.
- Use `0.3` when you want the current supported stable line with weekly OS/base-image refreshes.
- Use `stable` when you want the supported stable channel without caring about the numeric line tag.
- Use `latest` only as an alias of `stable`; it is not a separate policy channel.

Important:

- Exact release tags such as `0.3.0` must never be republished with different contents.
- Weekly rebuilds must never move `0.3.0`.
- `latest` must always point to the newest supported stable line.

## Release Workflow

The release workflow publishes all of the following tags for `0.3.0`:

- `0.3.0`
- `0.3`
- `stable`
- `latest`

This keeps a strict split between immutable release artifacts and floating stable-channel tags.

## Weekly Rebuild Workflow

The weekly rebuild workflow resolves the latest release tag in the supported `0.3.x` line and rebuilds that source with
the current container base image and OS packages.

The rebuild publishes:

- `0.3`
- `stable`
- `latest`
- `0.3-rYYYYMMDD`

The rebuild does not publish:

- `0.3.0`

## What Weekly Rebuilds Refresh

Weekly rebuilds refresh:

- Ubuntu base image layers
- APT packages installed during image build
- image metadata, SBOM, and provenance for the rebuilt artifact

Weekly rebuilds do not refresh:

- Python dependencies pinned by `uv.lock`
- application source code

Python dependency updates require a committed lockfile change and a new release build.

## Development Images

Development images are intentionally outside the stable contract.

Current development tags are:

- `edge-<branch>`
- `edge-sha-<gitsha>`

Development tags are mutable and unsupported for production use.

## Operational Guidance

- For production fleets that prioritize predictable rollbacks, pin `0.3.0`.
- For production fleets that prioritize automatic base-image security refreshes inside the supported line, use `0.3` or
  `stable`.
- If you use `latest`, treat it exactly the same as `stable`.
