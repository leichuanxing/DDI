FROM python:3.12-slim

ARG DDI_VERSION=0.0.0
ENV DDI_VERSION=$DDI_VERSION
LABEL org.opencontainers.image.version=$DDI_VERSION

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     DJANGO_SETTINGS_MODULE=ddi_system.settings

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends     default-libmysqlclient-dev build-essential pkg-config netcat-openbsd iputils-ping     && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY . /app
RUN chmod +x /app/docker/entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
