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
ARG PYTHON_IMAGE=3.12.7-alpine3.20
ARG ALPINE_IMAGE=3.20

########################################################################################################################
######################### BUILD ALPINE BASED IMAGE #####################################################################
########################################################################################################################
# First Alpine stage - build Python deps
FROM python:${PYTHON_IMAGE} AS builder

# Python version (minimal - 3.12)
ARG PYTHON_VERSION=3.12

# Copy and install dependencies
COPY requirements.txt .

RUN apk --no-cache add --virtual .build-deps \
        gcc python3-dev musl-dev linux-headers binutils && \
    python${PYTHON_VERSION} -m venv /venv && \
    /venv/bin/python -m ensurepip --upgrade && \
    /venv/bin/pip install --no-cache-dir -r requirements.txt && \
    find /venv/lib/python${PYTHON_VERSION}/site-packages/ -name '*.so' -exec strip --strip-unneeded {} + || true && \
    find /venv/lib/python${PYTHON_VERSION}/site-packages/ -type d -name 'tests' -exec rm -rf {} + || true && \
    find /venv/lib/python${PYTHON_VERSION}/site-packages/ -type d -name '__pycache__' -exec rm -rf {} + || true && \
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
    apk --no-cache add tzdata shadow

# Create a non-root user and group with restricted privileges
RUN groupadd -g 1033 docker && \
    useradd -u 1000 -g docker -m botuser && \
    usermod -aG docker botuser

# Set workdir and environment variables
WORKDIR /opt/app/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/app \
    PATH=/venv/bin:$PATH

# Copy necessary Python files and directories from first stage
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /usr/local/lib/ /usr/local/lib/
COPY --from=builder /venv /venv

# Copy app files in one step to reduce layers
COPY ./pytmbot ./pytmbot
COPY ./main.py ./main.py
COPY ./entrypoint.sh ./entrypoint.sh

# Set ownership of the app files to the new user
RUN chown -R botuser:docker /opt/app

# Make entrypoint script executable and set strict permissions
RUN chmod 700 ./entrypoint.sh

# Switch to the non-root user
USER botuser

########################################################################################################################
######################### TARGETS SETUP ###############################################################################
########################################################################################################################

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