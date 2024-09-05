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

COPY requirements.txt .

# Install all deps, activate venv, install and clean up
RUN apk --no-cache add gcc python3-dev musl-dev linux-headers && \
    python${PYTHON_VERSION} -m venv --without-pip venv && \
    pip install --upgrade --no-cache-dir --no-deps --target="/venv/lib/python${PYTHON_VERSION}/site-packages" -r requirements.txt && \
    python${PYTHON_VERSION} -m pip uninstall pip setuptools -y && \
    apk del gcc musl-dev linux-headers && \
    apk cache clean

# Second Alpine stage - based on the base stage. Setup bot
FROM alpine:${ALPINE_IMAGE} AS release_base

# Python version (minimal - 3.12)
ARG PYTHON_VERSION=3.12

# Update base os components and add timezone support
RUN apk --no-cache update && \
    apk --no-cache upgrade && \
    apk --no-cache add tzdata

# App workdir
WORKDIR /opt/app/

# Setup env vars
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/opt/app
ENV PATH=/venv/bin:$PATH

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