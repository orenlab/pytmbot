########################################################################################################################
#                                                                                                                      #
#                                               pyTMBot - Dockerfile                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
# Ubuntu-based multi-stage image with uv-locked dependencies and minimal runtime footprint.                           #
#                                                                                                                      #
########################################################################################################################

# syntax=docker/dockerfile:1.7

ARG UBUNTU_IMAGE=24.04
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.9.5
ARG COMPILE_BYTECODE=1

########################################################################################################################
######################### UV BINARY STAGE ##############################################################################
########################################################################################################################
FROM ${UV_IMAGE} AS uv_bin

########################################################################################################################
######################### BUILD STAGE ##################################################################################
########################################################################################################################
FROM ubuntu:${UBUNTU_IMAGE} AS builder

ARG DEBIAN_FRONTEND=noninteractive
ARG COMPILE_BYTECODE

WORKDIR /build

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    set -eux && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        build-essential \
        python3 \
        python3-dev \
        python3-venv \
        libffi-dev \
        libssl-dev \
        libjpeg-dev \
        zlib1g-dev \
        pkg-config \
        tzdata && \
    rm -rf /var/lib/apt/lists/*

COPY --from=uv_bin /uv /usr/local/bin/uv

ENV UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy

# Copy lock + project metadata first to maximize dependency-layer cache reuse.
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    set -eux && \
    uv sync \
        --frozen \
        --no-dev \
        --no-editable \
        --no-install-project \
        --python /usr/bin/python3

COPY pytmbot ./pytmbot

RUN set -eux && \
    if [ "$COMPILE_BYTECODE" = "1" ]; then \
        # Runtime uses PYTHONOPTIMIZE=1: compile a single opt-1 bytecode set
        # to avoid keeping duplicate non-optimized and optimized caches.
        python3 -m compileall -q -j 0 -o 1 /opt/venv /build/pytmbot; \
    fi

########################################################################################################################
######################### RUNTIME STAGE ################################################################################
########################################################################################################################
FROM ubuntu:${UBUNTU_IMAGE} AS runtime

ARG DEBIAN_FRONTEND=noninteractive

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    set -eux && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        python3 \
        tini \
        tzdata \
        passwd && \
    rm -rf /usr/share/doc/* /usr/share/man/* /usr/share/info/* && \
    rm -rf /var/lib/apt/lists/*

# Create runtime user and groups with stable UID/GID and docker-socket compatibility.
RUN groupadd --gid 1001 pytmbot && \
    useradd --uid 1001 --gid 1001 --create-home --home-dir /home/pytmbot --shell /usr/sbin/nologin pytmbot && \
    if ! getent group docker >/dev/null; then groupadd docker; fi && \
    usermod -aG docker,root pytmbot && \
    if getent group 1000 >/dev/null; then \
        usermod -aG "$(getent group 1000 | cut -d: -f1)" pytmbot; \
    else \
        groupadd --gid 1000 hostdocker && usermod -aG hostdocker pytmbot; \
    fi && \
    mkdir -p /opt/app && \
    chown -R pytmbot:pytmbot /opt/app && \
    chmod 750 /opt/app

WORKDIR /opt/app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/app \
    PATH=/opt/venv/bin:/usr/local/bin:/usr/bin:/bin \
    PYTHONFAULTHANDLER=1 \
    PYTHONHASHSEED=random \
    PYTHONOPTIMIZE=1 \
    PYTHONINSPECT=0 \
    TZ=UTC

# Copy virtual environment produced by uv from the builder image.
COPY --link --from=builder /opt/venv /opt/venv

# Keep compatibility with existing entrypoint absolute interpreter path.
RUN ln -sf /opt/venv/bin/python3 /usr/local/bin/python3 && \
    ln -sf /opt/venv/bin/python3 /usr/local/bin/python

COPY --link --chown=pytmbot:pytmbot --chmod=755 ./entrypoint.sh ./entrypoint.sh
# Copy app sources from builder to keep dependency layers cache-friendly.
COPY --link --from=builder --chown=1001:1001 /build/pytmbot ./pytmbot

# Basic runtime validation.
RUN python3 --version && test -x ./entrypoint.sh

HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \
    CMD ["./entrypoint.sh", "--health_check"]

########################################################################################################################
######################### TARGETS ######################################################################################
########################################################################################################################

FROM runtime AS production
USER pytmbot
ENTRYPOINT ["tini", "-s", "--", "./entrypoint.sh"]

FROM runtime AS self_build
COPY --chown=pytmbot:pytmbot pytmbot.yaml ./
USER pytmbot
ENTRYPOINT ["tini", "-s", "--", "./entrypoint.sh"]
