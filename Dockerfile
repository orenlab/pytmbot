# First stage
FROM python:3.12.2-alpine3.19 AS builder

# Copy python deps file
COPY requirements.txt .

# Install some python deps (needed for build psutil and over packages)
RUN apk --no-cache add gcc python3-dev musl-dev linux-headers

# Install dependencies to the venv path
RUN python3 -m venv --without-pip venv
RUN pip install --no-cache --target="/venv/lib/python3.12/site-packages" -r requirements.txt

# Second unnamed stage
FROM python:3.12.2-alpine3.19

# App workdir
WORKDIR /opt/pytmbot/

# Setup env var
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/opt/pytmbot
# Setup PATH env
ENV PATH=/venv/bin:$PATH
# Setup time zone
ENV TZ="Asia/Yekaterinburg"

# Copy .env file with token (prod, dev)
COPY .env /opt/pytmbot

# Copy only the dependencies installation from the 1st stage image
COPY --from=builder /venv /venv

# Copy bot files
COPY ./app ./app/
# Copy bot log
COPY ./logs /opt/logs/

# Update base os components
RUN apk --no-cache update && \
    apk --no-cache upgrade && \
# activate venv
    source /venv/bin/activate && \
# forward logs to Docker's log collector
    ln -sf /dev/stdout /opt/logs/pytmbot.log

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
