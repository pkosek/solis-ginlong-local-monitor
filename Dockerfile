FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY collector.py dashboard.py config.py start.sh ./
COPY templates/ templates/
COPY static/ static/

# Create data directory for SQLite
RUN mkdir -p /data

# Make startup script executable
RUN chmod +x start.sh

# Expose dashboard port
EXPOSE 5000

# Health check - hit the live API endpoint
HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/live')" || exit 1

ENTRYPOINT ["./start.sh"]
