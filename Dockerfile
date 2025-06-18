# Multi-arch build for Alpine with Python and Cron
FROM python:3.11-alpine

# Install required packages
RUN apk add --no-cache \
    tzdata \
    dcron \
    libcap \
    bash

# Create app directory
WORKDIR /app

# Copy Python requirements first (for better caching)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the sync scripts
COPY sync_to_trakt.py ./
COPY sync_to_trakt_wrapper.py ./

# Create directory for configuration
RUN mkdir -p /config

# Create a script for running sync
RUN echo '#!/bin/sh' > /app/run-sync.sh && \
    echo 'cd /app' >> /app/run-sync.sh && \
    echo 'python sync_to_trakt_wrapper.py' >> /app/run-sync.sh && \
    chmod +x /app/run-sync.sh

# Create entrypoint script
RUN echo '#!/bin/sh' > /entrypoint.sh && \
    echo '' >> /entrypoint.sh && \
    echo '# Set timezone if provided' >> /entrypoint.sh && \
    echo 'if [ -n "$TZ" ]; then' >> /entrypoint.sh && \
    echo '    cp /usr/share/zoneinfo/$TZ /etc/localtime' >> /entrypoint.sh && \
    echo '    echo "$TZ" > /etc/timezone' >> /entrypoint.sh && \
    echo 'fi' >> /entrypoint.sh && \
    echo '' >> /entrypoint.sh && \
    echo '# Setup cron if CRON_SCHEDULE is set' >> /entrypoint.sh && \
    echo 'if [ -n "$CRON_SCHEDULE" ]; then' >> /entrypoint.sh && \
    echo '    echo "Setting up cron with schedule: $CRON_SCHEDULE"' >> /entrypoint.sh && \
    echo '    echo "$CRON_SCHEDULE /app/run-sync.sh >> /var/log/sync.log 2>&1" | crontab -' >> /entrypoint.sh && \
    echo '    touch /var/log/sync.log' >> /entrypoint.sh && \
    echo '    echo "Starting crond..."' >> /entrypoint.sh && \
    echo '    crond -f -L /var/log/cron.log &' >> /entrypoint.sh && \
    echo '    echo "Following sync log..."' >> /entrypoint.sh && \
    echo '    tail -f /var/log/sync.log' >> /entrypoint.sh && \
    echo 'else' >> /entrypoint.sh && \
    echo '    echo "No CRON_SCHEDULE set, running sync once"' >> /entrypoint.sh && \
    echo '    exec /app/run-sync.sh' >> /entrypoint.sh && \
    echo 'fi' >> /entrypoint.sh && \
    chmod +x /entrypoint.sh

# Expose volume for persistent token storage
VOLUME ["/config"]

# Set environment variables (can be overridden)
ENV PYTHONUNBUFFERED=1 \
    TZ=Europe/Warsaw

ENTRYPOINT ["/entrypoint.sh"]
