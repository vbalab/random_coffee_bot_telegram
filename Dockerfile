FROM python:3.12.10-slim

WORKDIR /usr/src/app

RUN apt-get update \
    && apt-get install -y nano iputils-ping vim tmux \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --retries=20 --timeout=60 --resume-retries=20 -r requirements.txt

ENV PYTHONPATH=/usr/src/app/src

COPY .env ./
COPY src/ src/
COPY docs/ docs/
