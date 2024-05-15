#######################################
# pyTMbot Dockerfile (based on Ubuntu)
# image size: ~ 180Mb
# https://github.com/orenlab/pytmbot
#######################################

# Set Ubuntu tag version
ARG IMAGE_VERSION=24.04

# First stage
FROM ubuntu:${IMAGE_VERSION} AS builder
# Python version (minimal - 3.12)
ARG PYTHON_VERSION=3.12
ARG DEBIAN_FRONTEND=noninteractive

# Update base os components and install all deps (need to build psutil)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    python3-wheel \
    python3-dev \
    build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get autoclean -y

# Copy app deps
COPY requirements.txt .

# Install dependencies to the venv path
RUN python${PYTHON_VERSION} -m venv --without-pip venv
RUN python${PYTHON_VERSION} -m pip install --target="/venv/lib/python${PYTHON_VERSION}/site-packages" \
    -r requirements.txt

RUN apt-get remove -y python3-pip python3-wheel python3-dev build-essential

# Second unnamed stage
FROM ubuntu:$IMAGE_VERSION
# Python version (minimal - 3.12)
ARG PYTHON_VERSION=3.12
ARG DEBIAN_FRONTEND=noninteractive

# Update base os components and install minimal deps
RUN apt-get update && apt-get upgrade -y && apt-get clean && \
    apt-get install -y --no-install-recommends \
    python3 \
  && apt-get clean \
  && rm -rf /var/cache/apt/archives /var/lib/apt/lists/*

# App workdir
WORKDIR /opt/pytmbot/

# Setup env var
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/opt/pytmbot
ENV PATH=/venv/bin:$PATH
# Setup time zone (can ovveride on docker run args)
ENV TZ="Asia/Yekaterinburg"

# Copy only the dependencies installation from the first stage image
COPY --from=builder /venv /venv

# Copy lisence
COPY LICENSE /opt/pytmbot

# Copy bot files
COPY ./app ./app/
COPY ./logs /opt/logs/

# forward logs to Docker's log collector
RUN ln -sf /dev/stdout /opt/logs/pytmbot.log

# Run app
# !!! needed set log level:
#   - DEBUG
#   - INFO (default)
#   - ERROR
#   - CRITICAL
# !!! needed set pyTMBot mode:
#   - dev
#   - prod (default)
CMD [ "/venv/bin/python3", "app/main.py", "--log-level=INFO", "--mode=prod" ]
