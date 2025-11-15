FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps (optional: for SSL/CA and timezone)
RUN apt-get update -y && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy app
COPY . /app

# Expose port
EXPOSE 8000

# Default command (App Runner/containers)
CMD ["gunicorn", "-w", "2", "-k", "gthread", "-t", "120", "-b", "0.0.0.0:8000", "src.app_modular:app"]


