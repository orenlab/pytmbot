########################################################################################################################
#                                                                                                                      #
#                                               pyTMBot - Dockerfile                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
# A lightweight Telegram bot for managing Docker containers and images, monitoring server statuses,                    #
# and extending its functionality with plugins.                                                                        #
#                                                                                                                      #
# Project:        pyTMBot                                                                                              #
# Author:         Denis Rozhnovskiy <pytelemonbot@mail.ru>                                                             #
# Repository:     https://github.com/orenlab/pytmbot                                                                   #
# License:        MIT                                                                                                  #
# Description:    This Dockerfile builds a secure, minimal image based on Alpine Linux with Python 3.13.               #
#                 It includes a Docker socket for managing containers without requiring root access for other tasks.   #
#                                                                                                                      #
########################################################################################################################

# Set base images tag
ARG PYTHON_IMAGE=3.13-alpine3.22
ARG ALPINE_IMAGE=3.22

########################################################################################################################
######################### BUILD ALPINE BASED IMAGE ####################################################################
########################################################################################################################
# First Alpine stage - build Python deps
FROM python:${PYTHON_IMAGE} AS builder

# Python version
ARG PYTHON_VERSION=3.13

# Install build dependencies and create virtual environment
WORKDIR /build
COPY requirements.txt .

RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/var/cache/apk \
    apk add --no-cache --virtual .build-deps \
        gcc python3-dev musl-dev linux-headers binutils && \
    python -m venv /venv && \
    /venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel && \
    /venv/bin/pip install --no-cache-dir -r requirements.txt && \
    # Optimize installed packages
    find /venv -name '*.pyc' -delete && \
    find /venv -name '*.pyo' -delete && \
    find /venv -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true && \
    find /venv -name 'tests' -type d -exec rm -rf {} + 2>/dev/null || true && \
    find /venv -name '*.dist-info' -type d -exec rm -rf {} + 2>/dev/null || true && \
    find /venv -name '*.so' -exec strip --strip-unneeded {} + 2>/dev/null || true && \
    find /venv -name '*.a' -delete && \
    find /venv -name '*.h' -delete && \
    find /venv -name '*.egg-info' -type d -exec rm -rf {} + 2>/dev/null || true && \
    apk del .build-deps

########################################################################################################################
######################### SETUP FINAL IMAGE ############################################################################
########################################################################################################################
# Second Alpine stage - setup bot environment
FROM alpine:${ALPINE_IMAGE} AS release_base

# Python version
ARG PYTHON_VERSION=3.13

# Create app user first (simpler approach)
RUN --mount=type=cache,target=/var/cache/apk \
    apk add --no-cache \
        tzdata && \
    # Create app user with a safe UID
    adduser -D -u 1001 -s /bin/sh pytmbot && \
    # Create docker group (we'll handle GID at runtime)
    addgroup docker && \
    addgroup pytmbot docker && \
    # Clean up
    rm -rf /var/cache/apk/* /tmp/*

# Set workdir and environment variables
WORKDIR /opt/app/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/app \
    PATH=/venv/bin:$PATH \
    PYTHONFAULTHANDLER=1 \
    PYTHONHASHSEED=random \
    PYTHONOPTIMIZE=2

# Copy virtual environment from builder
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /usr/local/lib/ /usr/local/lib/
COPY --from=builder /venv /venv

# Copy app files
COPY ./pytmbot ./pytmbot
COPY ./entrypoint.sh ./entrypoint.sh

# Set permissions and ownership
RUN chmod 755 ./entrypoint.sh && \
    chown -R pytmbot:docker /opt/app && \
    chown -R pytmbot:docker /venv

# Add health check
#HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
#    CMD ["python", "-c", "import sys; sys.exit(0)"]

########################################################################################################################
######################### TARGETS SETUP ################################################################################
########################################################################################################################

# Target for CI/CD image
FROM release_base AS production

# Switch to non-root user
USER pytmbot

ENTRYPOINT ["./entrypoint.sh"]

# Target for self build image, --mode = prod
FROM release_base AS self_build

# Copy config file with token (prod, dev)
COPY pytmbot.yaml ./

# Set ownership
RUN chown pytmbot:docker pytmbot.yaml

# Switch to non-root user
USER pytmbot

ENTRYPOINT ["./entrypoint.sh"]