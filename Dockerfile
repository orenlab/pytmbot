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
# Description:    Dockerfile using pyproject.toml with security improvements.                                          #
#                                                                                                                      #
########################################################################################################################

# Set base images tag
ARG PYTHON_IMAGE=3.13.12-alpine3.23
ARG ALPINE_IMAGE=3

########################################################################################################################
######################### BUILD DEPENDENCIES STAGE #####################################################################
########################################################################################################################
FROM python:${PYTHON_IMAGE} AS builder

WORKDIR /build

# Copy project files and source code for pip to resolve dependencies
COPY pyproject.toml poetry.lock* ./
COPY pytmbot ./pytmbot
RUN touch README.md 2>/dev/null || true

# Install dependencies directly from pyproject.toml using pip
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/var/cache/apk \
    set -eux && \
    # Validate project files
    test -f pyproject.toml || (echo "ERROR: pyproject.toml not found" && exit 1) && \
    # Install build dependencies
    apk add --no-cache --virtual .build-deps \
        gcc python3-dev musl-dev linux-headers binutils && \
    # Upgrade pip to ensure pyproject.toml support
    pip install --no-cache-dir --upgrade pip setuptools wheel build && \
    # Install only runtime dependencies (excluding dev/test groups)
    pip install --no-cache-dir --target /packages . && \
    # Clean up build dependencies
    apk del .build-deps && \
    # Strip debug symbols from compiled extensions
    find /packages -name "*.so" -exec strip --strip-unneeded {} + 2>/dev/null || true && \
    # Show final package size
    echo "=== PACKAGES SIZE ===" && \
    du -sh /packages

########################################################################################################################
######################### OPTIMIZATION STAGE ###########################################################################
########################################################################################################################
FROM python:${PYTHON_IMAGE} AS optimizer

COPY --from=builder /packages /packages

# Enhanced cleanup with security focus
RUN cd /packages && \
    echo "=== OPTIMIZING PACKAGES ===" && \
    # Remove Python bytecode and cache
    find . -name '*.pyc' -delete && \
    find . -name '*.pyo' -delete && \
    find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true && \
    # Remove tests and docs
    find . -name 'tests' -type d -exec rm -rf {} + 2>/dev/null || true && \
    find . -name 'test' -type d -exec rm -rf {} + 2>/dev/null || true && \
    find . -type d -name 'doc' -exec rm -rf {} + 2>/dev/null || true && \
    find . -type d -name 'docs' -exec rm -rf {} + 2>/dev/null || true && \
    find . -type d -name 'examples' -exec rm -rf {} + 2>/dev/null || true && \
    # Remove metadata
    find . -name '*.dist-info' -type d -exec rm -rf {} + 2>/dev/null || true && \
    find . -name '*.egg-info' -type d -exec rm -rf {} + 2>/dev/null || true && \
    # Strip binaries
    find . -name '*.so' -exec strip --strip-unneeded {} + 2>/dev/null || true && \
    find . -name '*.so.*' -exec strip --strip-unneeded {} + 2>/dev/null || true && \
    # Remove development files
    find . -name '*.a' -delete 2>/dev/null || true && \
    find . -name '*.h' -delete 2>/dev/null || true && \
    find . -type d -name 'include' -exec rm -rf {} + 2>/dev/null || true && \
    # Remove pip, setuptools, wheel completely
    rm -rf pip* setuptools* wheel* pkg_resources* _distutils_hack* distutils* && \
    echo "=== OPTIMIZED PACKAGES SIZE ===" && \
    du -sh /packages && \
    du -sh /packages/* 2>/dev/null | sort -hr | head -10

########################################################################################################################
######################### PYTHON EXTRACTOR STAGE #######################################################################
########################################################################################################################
FROM python:${PYTHON_IMAGE} AS python_extractor

ARG PYTHON_VERSION=3.13

# Extract minimal Python runtime
RUN mkdir -p /python_minimal/bin /python_minimal/lib && \
    # Copy only essential binaries
    cp /usr/local/bin/python${PYTHON_VERSION} /python_minimal/bin/ && \
    ln -sf python${PYTHON_VERSION} /python_minimal/bin/python3 && \
    ln -sf python${PYTHON_VERSION} /python_minimal/bin/python && \
    # Copy Python standard library
    cp -r /usr/local/lib/python${PYTHON_VERSION} /python_minimal/lib/ && \
    # Copy shared libraries
    find /usr/local/lib -name "libpython*.so*" -exec cp {} /python_minimal/lib/ \; && \
    # Clean up standard library (conservative approach)
    cd /python_minimal/lib/python${PYTHON_VERSION} && \
    rm -rf test tests tkinter turtle* idlelib ensurepip && \
    find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true && \
    find . -name '*.pyc' -delete && \
    find . -type d -name 'doc' -exec rm -rf {} + 2>/dev/null || true && \
    echo "=== PYTHON MINIMAL SIZE ===" && \
    du -sh /python_minimal

########################################################################################################################
######################### RUNTIME STAGE #################################################################################
########################################################################################################################
FROM alpine:${ALPINE_IMAGE} AS runtime

ARG PYTHON_VERSION=3.13

# Install minimal runtime dependencies
RUN apk update && apk upgrade --no-cache && \
    # Install only essential packages
    apk add --no-cache \
        libssl3 libcrypto3 libffi zlib readline sqlite-libs tzdata \
        su-exec tini && \
    # Create docker group with default GID (will be adjusted by entrypoint)
    addgroup docker && \
    # Create user with fixed UID for consistency
    adduser -D -u 1001 -s /bin/sh pytmbot && \
    adduser pytmbot docker && \
    # Create directories
    mkdir -p /opt/app && \
    chown -R pytmbot:pytmbot /opt/app && \
    chmod 750 /opt/app && \
    # Security cleanup
    rm -rf /var/cache/apk/* /var/lib/apk/lists/* /tmp/* /root/.cache \
           /usr/share/man /usr/share/doc

WORKDIR /opt/app

# Set environment with security improvements
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/app:/opt/packages \
    PATH=/usr/local/bin:$PATH \
    PYTHONFAULTHANDLER=1 \
    PYTHONHASHSEED=random \
    PYTHONOPTIMIZE=1 \
    PYTHONINSPECT=0 \
    TZ=UTC

# Copy Python runtime
COPY --from=python_extractor /python_minimal/bin/* /usr/local/bin/
COPY --from=python_extractor /python_minimal/lib /usr/local/lib/

# Copy optimized packages
COPY --from=optimizer --chown=pytmbot:pytmbot /packages /opt/packages

# Copy application with proper permissions
COPY --chown=pytmbot:pytmbot --chmod=755 ./entrypoint.sh ./entrypoint.sh
COPY --chown=pytmbot:pytmbot ./pytmbot ./pytmbot

# Verify installation
RUN python3 --version && \
    test -x ./entrypoint.sh

# Health check
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