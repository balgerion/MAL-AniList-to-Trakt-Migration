FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    cron \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir requests tqdm

COPY sync_to_trakt.py .
COPY entrypoint.sh .
COPY run_sync.sh .

RUN chmod +x entrypoint.sh run_sync.sh

RUN mkdir -p /app/data /app/logs

ENV TRAKT_CLIENT_ID=""
ENV TRAKT_CLIENT_SECRET=""
ENV DATA_SOURCE="MAL"
ENV MAL_CLIENT_ID=""
ENV MAL_USERNAME=""
ENV ANILIST_USERNAME=""
ENV RUN_MODE="once"
ENV CRON_SCHEDULE="0 3 * * *"

ENTRYPOINT ["/app/entrypoint.sh"]
