# syntax=docker/dockerfile:1
#
# harqis-work runtime image.
# Default CMD runs a Celery worker; override with `python run_workflows.py beat`
# or `uvicorn frontend.main:app ...` for other roles. See docker-compose.yml.
#
# Build args:
#   PYTHON_VERSION  base Python (default 3.12)
#   ENV             runtime environment label (default production)

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS base

WORKDIR /app

# System deps. build-essential + python3-dev are needed for any sdist deps in
# requirements.txt; rm apt lists to keep the layer small.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        curl \
        build-essential \
        python3-dev \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 harqis

# Use a venv inside the image so PATH is predictable and the harqis user owns it.
RUN python -m venv /app/venv \
    && chown -R harqis:harqis /app
ENV PATH=/app/venv/bin:$PATH

# Install Python deps as the non-root user from this point on.
USER harqis

# Cache layer: only requirements first.
COPY --chown=harqis:harqis requirements.txt .

# mcp pulls anyio>=4.5 but harqis-core pins anyio==4.3.0, so install base deps
# first, then upgrade anyio, then add mcp on top. Keep these on one RUN to avoid
# blowing up the layer count.
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install --upgrade anyio \
    && pip install "mcp>=1.0.0"

# Application code (after deps so code edits don't bust the pip cache).
COPY --chown=harqis:harqis . .

# Runtime config. ENV is parameterised so dev/staging/prod images differ only
# by build arg, not by Dockerfile edits.
ARG ENV=production
ENV PYTHONPATH=/app \
    ENV_ROOT_DIRECTORY=/app \
    ENV=${ENV}

# Persist task-emitted artifacts and let the operator mount real secrets.
VOLUME ["/app/data", "/app/.env"]

# Lightweight liveness probe: import the workflows package. Catches missing deps
# or broken imports without needing a broker connection.
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import workflows" || exit 1

# Default to a Celery worker on the `default` queue. Override per-service in
# docker-compose.yml (beat, frontend, etc.) via `command:`.
CMD ["python", "run_workflows.py", "worker"]
