#############################################################
## pyTMbot Dockerfile
# https://github.com/orenlab/pytmbot
#
# To launch with a production token. Default way:
# docker --target prod build -t orenlab/pytmbot:latest .
#
# To launch with a development token. Only for development:
# docker --target dev build -t orenlab/pytmbot:latest .
#############################################################

# Set base images tag
ARG PYTHON_IMAGE=alpine3.20
ARG ALPINE_IMAGE=3.20

########################################################################################################################
######################### BUILD ALPINE BASED IMAGE #####################################################################
########################################################################################################################

# Zero Alpine stage - setup base image
FROM alpine:${ALPINE_IMAGE} AS alpine_base

# Update base os components
RUN apk --no-cache update && \
    apk --no-cache upgrade && \
# Add Timezone support in Alpine image
    apk --no-cache add tzdata

# App workdir
WORKDIR /opt/pytmbot/

# Setup env var
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/opt/pytmbot
ENV PATH=/venv/bin:$PATH

# Copy lisence
COPY LICENSE /opt/pytmbot/

# Copy bot files
COPY ./app ./app/

# First Alpine stage - build Python deps
FROM python:${PYTHON_IMAGE} AS builder

# Python version (minimal - 3.12)
ARG PYTHON_VERSION=3.12

COPY requirements.txt .

# Install all deps (need to build psutil)
RUN apk --no-cache add gcc python3-dev musl-dev linux-headers

# Install dependencies to the venv path
RUN python${PYTHON_VERSION} -m venv --without-pip venv
RUN pip install --no-cache-dir --no-deps --target="/venv/lib/python${PYTHON_VERSION}/site-packages"  \
    -r requirements.txt --upgrade

RUN python${PYTHON_VERSION} -m pip uninstall pip setuptools python3-wheel python3-dev musl-dev -y

# Second Alpine stage - based on the base stage. Setup bot
FROM alpine_base AS reliase_base

# Python version (minimal - 3.12)
ARG PYTHON_VERSION=3.12

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

# Target for CI/CD image, --mode = prod
FROM reliase_base AS prod

CMD [ "/venv/bin/python3", "app/main.py", "--log-level=INFO", "--mode=prod" ]

# Target for self biuld image, --mode = prod
FROM reliase_base AS selfbuild_prod

# Copy .pytmbotenv file with token (prod, dev)
COPY .pytmbotenv /opt/pytmbot/

CMD [ "/venv/bin/python3", "app/main.py", "--log-level=INFO", "--mode=prod" ]

# Target for self biuld image, --mode = dev
FROM reliase_base AS selfbuild_dev

# Copy .pytmbotenv file with token (prod, dev)
COPY .pytmbotenv /opt/pytmbot/

CMD [ "/venv/bin/python3", "app/main.py", "--log-level=DEBUG", "--mode=dev" ]