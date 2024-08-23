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

# Install all deps (need to build psutil)
RUN apk --no-cache add gcc python3-dev musl-dev linux-headers && \
# Activate venv
    python${PYTHON_VERSION} -m venv --without-pip venv && \
# Install deps
    pip install --upgrade --no-cache-dir --no-deps --target="/venv/lib/python${PYTHON_VERSION}/site-packages"  \
    -r requirements.txt --upgrade &&  \
# Uninstall build deps
    python${PYTHON_VERSION} -m pip uninstall pip setuptools -y && \
    apk del gcc musl-dev linux-headers

# Second Alpine stage - based on the base stage. Setup bot
FROM alpine:${ALPINE_IMAGE}  AS reliase_base

# Python version (minimal - 3.12)
ARG PYTHON_VERSION=3.12

# Update base os components
RUN apk --no-cache update && \
    apk --no-cache upgrade && \
# Add Timezone support in Alpine image
    apk --no-cache add tzdata

# App workdir
WORKDIR /opt/app/

# Setup env var
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/opt/app
ENV PATH=/venv/bin:$PATH

# Copy bot files
COPY ./pytmbot ./pytmbot
COPY ./main.py ./main.py


# Сopy only the necessary python files and directories from first stage
COPY --from=builder /usr/local/bin/python3 /usr/local/bin/python3
COPY --from=builder /usr/local/bin/python${PYTHON_VERSION} /usr/local/bin/python${PYTHON_VERSION}
COPY --from=builder /usr/local/lib/python${PYTHON_VERSION} /usr/local/lib/python${PYTHON_VERSION}
COPY --from=builder /usr/local/lib/libpython${PYTHON_VERSION}.so.1.0 /usr/local/lib/libpython${PYTHON_VERSION}.so.1.0
COPY --from=builder /usr/local/lib/libpython3.so /usr/local/lib/libpython3.so

# Copy only the dependencies installation from the first stage image
COPY --from=builder /venv /venv

# activate venv
RUN source /venv/bin/activate && \
# forward logs to Docker's log collector
    ln -sf /dev/stdout /dev/stdout && \
    ln -sf /dev/stderr /dev/stderr

# Target for CI/CD image
FROM reliase_base AS production

ENTRYPOINT [ "/venv/bin/python3", "main.py" ]

# Target for self biuld image, --mode = prod
FROM reliase_base AS self_build

# Copy .pytmbotenv file with token (prod, dev)
COPY pytmbot.yaml /opt/app/

ENTRYPOINT [ "/venv/bin/python3", "main.py" ]

# Target for CI/CD stable tag (0.0.9, 0.1.1, latest)
FROM reliase_base AS prod

ENTRYPOINT [ "/venv/bin/python3", "main.py" ]