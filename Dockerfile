#############################################################
# (c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
# pyTMBot - A simple Telegram bot to handle Docker containers and images,
# also providing basic information about the status of local servers.
# https://github.com/orenlab/pytmbot
# License: MIT
#############################################################

# Set base images tag
ARG PYTHON_IMAGE=3.12.7-alpine3.20
ARG ALPINE_IMAGE=3.20

########################################################################################################################
######################### BUILD ALPINE BASED IMAGE #####################################################################
########################################################################################################################
# First Alpine stage - build Python deps
FROM python:${PYTHON_IMAGE} AS builder

# Python version (minimal - 3.12)
ARG PYTHON_VERSION=3.12

RUN apk --no-cache update && \
    apk --no-cache upgrade

# Copy and install dependencies
COPY requirements.txt .

RUN apk --no-cache add --virtual .build-deps gcc python3-dev musl-dev linux-headers binutils && \
    python${PYTHON_VERSION} -m venv /venv && \
    /venv/bin/python -m ensurepip --upgrade && \
    /venv/bin/pip install --upgrade --no-cache-dir --target="/venv/lib/python${PYTHON_VERSION}/site-packages" -r requirements.txt && \
    /venv/bin/pip uninstall -y pip setuptools wheel || echo "No module to uninstall" && \
    find /venv/lib/python${PYTHON_VERSION}/site-packages/ -name '*.so' -exec strip --strip-unneeded {} + || echo "No *.so to strip" && \
    find /venv/lib/python${PYTHON_VERSION}/site-packages/ -type d -name 'tests' -exec rm -rf {} + || echo "No tests to remove" && \
    find /venv/lib/python${PYTHON_VERSION}/site-packages/ -type d -name '__pycache__' -exec rm -rf {} + || echo "No __pycache__ to remove" && \
    find /venv/lib/python${PYTHON_VERSION}/site-packages/ -name '*.pyc' -exec rm -rf {} + || echo "No *.pyc to remove" && \
    find /usr/local/lib/python${PYTHON_VERSION}/ -name 'pip*' -exec rm -rf {} + || echo "No pip to remove" && \
    find /usr/local/lib/python${PYTHON_VERSION}/ -name 'setuptools*' -exec rm -rf {} + || echo "No setuptools to remove" && \
    find /usr/local/lib/python${PYTHON_VERSION}/ -name 'wheel*' -exec rm -rf {} + || echo "No wheel to remove" && \
    apk del .build-deps && \
    rm -rf /root/.cache

########################################################################################################################
######################### SETUP FINAL IMAGE ###########################################################################
########################################################################################################################
# Second Alpine stage - setup bot environment
FROM alpine:${ALPINE_IMAGE} AS release_base

# Python version (minimal - 3.12)
ARG PYTHON_VERSION=3.12

# Update and install essential packages in a single step
RUN apk --no-cache upgrade && \
    apk add --no-cache tzdata

# Set workdir and environment variables
WORKDIR /opt/app/
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/app \
    PATH=/venv/bin:$PATH

# Copy app files in one step to reduce layers
COPY ./pytmbot ./pytmbot
COPY ./main.py ./main.py
COPY ./entrypoint.sh ./entrypoint.sh

# Make entrypoint script executable
RUN chmod +x ./entrypoint.sh

# Copy necessary Python files and directories from first stage
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /usr/local/lib/ /usr/local/lib/
COPY --from=builder /venv /venv

# Target for CI/CD image
FROM release_base AS production

ENTRYPOINT ["./entrypoint.sh"]

# Target for self build image, --mode = prod
FROM release_base AS self_build

# Copy config file with token (prod, dev)
COPY pytmbot.yaml ./

ENTRYPOINT ["./entrypoint.sh"]

# Target for CI/CD stable tag (0.0.9, 0.1.1, latest)
FROM release_base AS prod

ENTRYPOINT ["./entrypoint.sh"]