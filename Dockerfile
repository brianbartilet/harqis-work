# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim

WORKDIR /app

# Optional data mount point
VOLUME ["/app/data"]

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Create venv first
RUN python -m venv /app/venv
ENV PATH=/app/venv/bin:$PATH

# Copy only requirements first for better Docker layer caching
COPY requirements.txt .

# Upgrade pip and install Python deps.
# mcp requires anyio>=4.5 but harqis-core pins anyio==4.3.0.
# Install base deps first, upgrade anyio, then install mcp separately.
RUN python -m pip install --upgrade pip && \
    pip install -r requirements.txt && \
    pip install --upgrade anyio && \
    pip install "mcp>=1.0.0"

# If harqis-core pulls Playwright and you need browser automation at runtime,
# install browser dependencies + Chromium
# RUN playwright install --with-deps chromium

# Copy the rest of the app
COPY . .

# Runtime env vars
ENV PYTHONPATH=/app
ENV ENV_ROOT_DIRECTORY=/app
ENV ENV=TEST

# Uncomment the one you want
# RUN python get_started.py
# CMD ["pytest"]