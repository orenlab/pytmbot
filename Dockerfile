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
# Description:    This Dockerfile builds a secure, minimal image based on Alpine Linux with Python 3.12.               #
#                 It includes a Docker socket for managing containers without requiring root access for other tasks.   #
#                                                                                                                      #
########################################################################################################################

# Set base images tag
ARG PYTHON_IMAGE=3.13-alpine3.22
ARG ALPINE_IMAGE=3.22

########################################################################################################################
######################### BUILD DEPENDENCIES STAGE #####################################################################
########################################################################################################################
FROM python:${PYTHON_IMAGE} AS builder

WORKDIR /build
COPY requirements.txt .

# Install packages directly to site-packages without venv
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/var/cache/apk \
    apk add --no-cache --virtual .build-deps \
        gcc python3-dev musl-dev linux-headers binutils && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt --target /packages && \
    apk del .build-deps && \
    echo "=== PACKAGES SIZE ===" && \
    du -sh /packages

########################################################################################################################
######################### OPTIMIZATION STAGE ###########################################################################
########################################################################################################################
FROM python:${PYTHON_IMAGE} AS optimizer

COPY --from=builder /packages /packages

# Ultra-aggressive cleanup
RUN cd /packages && \
    # Remove all bytecode and cache
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
    # Clean up standard library
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
RUN apk add --no-cache \
        libssl3 libcrypto3 libffi zlib readline sqlite-libs tzdata && \
    adduser -D -u 1001 -s /bin/sh pytmbot && \
    addgroup docker && \
    adduser pytmbot docker && \
    mkdir -p /opt/app && \
    chown -R pytmbot:docker /opt/app && \
    rm -rf /var/cache/apk/* /tmp/*

WORKDIR /opt/app

# Set environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/app:/opt/packages \
    PATH=/usr/local/bin:$PATH \
    PYTHONFAULTHANDLER=1 \
    PYTHONHASHSEED=random

# Copy Python runtime
COPY --from=python_extractor /python_minimal/bin/* /usr/local/bin/
COPY --from=python_extractor /python_minimal/lib /usr/local/lib/

# Copy optimized packages
COPY --from=optimizer --chown=pytmbot:docker /packages /opt/packages

# Copy application
COPY --chown=pytmbot:docker --chmod=755 ./entrypoint.sh ./entrypoint.sh
COPY --chown=pytmbot:docker ./pytmbot ./pytmbot

# Health check
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys; sys.exit(0)"]

########################################################################################################################
######################### TARGETS ######################################################################################
########################################################################################################################

FROM runtime AS production
USER pytmbot
ENTRYPOINT ["./entrypoint.sh"]

FROM runtime AS self_build
COPY --chown=pytmbot:docker pytmbot.yaml ./
USER pytmbot
ENTRYPOINT ["./entrypoint.sh"]