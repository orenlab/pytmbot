#############################################################
# (c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
# pyTMBot - A simple Telegram bot to handle Docker containers and images,
# also providing basic information about the status of local servers.
# https://github.com/orenlab/pytmbot
# License: MIT
#############################################################

# Set base images tag
ARG PYTHON_IMAGE=alpine3.20
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
    /venv/bin/pip uninstall -y pip setuptools wheel && \
    find /venv/lib/python${PYTHON_VERSION}/site-packages/ -name '*.so' -exec strip --strip-unneeded {} + && \
    find /venv/lib/python${PYTHON_VERSION}/site-packages/ -type d -name 'tests' -exec rm -rf {} + && \
    find /venv/lib/python${PYTHON_VERSION}/site-packages/ -type d -name '__pycache__' -exec rm -rf {} + && \
    find /venv/lib/python${PYTHON_VERSION}/site-packages/ -name '*.pyc' -exec rm -rf {} + && \
    python3 -m pip uninstall -y pip setuptools wheel && \
    find /usr/local/lib/python${PYTHON_VERSION}/ -name 'pip*' -exec rm -rf {} + && \
    find /usr/local/lib/python${PYTHON_VERSION}/ -name 'setuptools*' -exec rm -rf {} + && \
    find /usr/local/lib/python${PYTHON_VERSION}/ -name 'wheel*' -exec rm -rf {} + && \
    apk del .build-deps && \
    rm -rf /root/.cache

########################################################################################################################
######################### SETUP FINAL IMAGE ###########################################################################
########################################################################################################################
# Second Alpine stage - setup bot environment
FROM alpine:${ALPINE_IMAGE} AS release_base

# Python version (minimal - 3.12)
ARG PYTHON_VERSION=3.12

# Update and install only essential packages
RUN apk --no-cache update && \
    apk --no-cache upgrade && \
    apk --no-cache add tzdata

# App workdir
WORKDIR /opt/app/

# Setup environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/app \
    PATH=/venv/bin:$PATH

# Copy bot files
COPY ./pytmbot ./pytmbot
COPY ./main.py ./main.py
COPY ./entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

# Copy necessary Python files and directories from first stage
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /usr/local/lib/ /usr/local/lib/
COPY --from=builder /venv /venv

# Activate venv and setup logging
RUN source /venv/bin/activate && \
    ln -sf /dev/stdout /dev/stdout && \
    ln -sf /dev/stderr /dev/stderr

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