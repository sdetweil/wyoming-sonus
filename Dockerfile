FROM python:3.11-slim-bookworm

ENV LANG C.UTF-8
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install --yes --no-install-recommends avahi-utils

WORKDIR /app

COPY script/setup ./script/
COPY setup.py requirements.txt MANIFEST.in ./
COPY sonushandler/ ./sonushandler/

RUN script/setup

COPY script/run ./script/
COPY docker/run ./


EXPOSE 8080

ENTRYPOINT ["/app/run"]
