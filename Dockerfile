FROM python:3.11-slim

# Install ffmpeg, curl and ca-certificates
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Configure environment variables
ENV PORT=3000
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8

# Expose port for Alet Cloud / container readiness probes
EXPOSE 3000

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Run the Telegram bot and cloud healthcheck server
CMD ["python", "bot.py"]
