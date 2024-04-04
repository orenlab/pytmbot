# first stage
FROM python:3.12.2-alpine3.19 AS builder
COPY requirements.txt .

RUN apk --no-cache add gcc python3-dev musl-dev linux-headers

# install dependencies to the venv path
RUN python3 -m venv --without-pip venv
RUN pip install --no-cache --target="/venv/lib/python3.12/site-packages" -r requirements.txt

# second unnamed stage
FROM python:3.12.2-alpine3.19

# App workdir
WORKDIR /opt/pytmbot/

# Setup env var
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/opt/pytmbot
ENV PATH=/venv/bin:$PATH
ENV TZ="Asia/Yekaterinburg"

# Copy .env file with token (prod, dev)
COPY .env /opt/pytmbot

# copy only the dependencies installation from the 1st stage image
COPY --from=builder /venv /venv
COPY ./app ./app/
COPY ./logs /opt/logs/

# update base os components
RUN apk update && \
    apk upgrade && \
    apk cache clean && \
# activate venv
    source /venv/bin/activate && \
# forward logs to Docker's log collector
    ln -sf /dev/stdout /opt/logs/pytmbot.log

# run app
# !!! needed set log level:
#   - DEBUG
#   - INFO (default)
#   - ERROR
#   - CRITICAL
# !!! needed set pyTMBot mode:
#   - dev
#   - prod (default)
CMD [ "/venv/bin/python3", "app/main.py", "--log-level=INFO", "--mode=prod" ]
