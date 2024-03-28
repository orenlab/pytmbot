# first stage
FROM python:3.12.2-alpine AS builder
COPY requirements.txt .

RUN apk --no-cache add gcc python3-dev musl-dev linux-headers

# install dependencies to the venv path
RUN python3 -m venv --without-pip venv
RUN pip install --no-cache --target="/venv/lib/python3.12/site-packages" -r requirements.txt

# second unnamed stage
FROM python:3.12.2-alpine

# update base os components
RUN apk update && apk upgrade && apk cache clean

# App workdir
WORKDIR /opt/pytmbot/

# Copy .env file with token (prod, dev)
COPY .env /opt/pytmbot

# copy only the dependencies installation from the 1st stage image
COPY --from=builder /venv /venv
COPY ./app ./app/
COPY ./logs /opt/logs/

RUN source /venv/bin/activate

# update PATH environment variable
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH=/opt/pytmbot
ENV PATH=/venv/bin:$PATH

# Change TZ!
ENV TZ="Asia/Yekaterinburg"

# forward logs to Docker's log collector
RUN ln -sf /dev/stdout /opt/logs/pytmbot.log


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
