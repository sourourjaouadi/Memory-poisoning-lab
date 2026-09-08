FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast, reliable package installations
RUN pip install --no-cache-dir uv

# Copy requirements and install
COPY requirements.txt .
RUN uv pip install --system -r requirements.txt

# Copy application source code
COPY agent/ ./agent/
COPY memory/ ./memory/
COPY tools/ ./tools/
COPY scenarios/ ./scenarios/
COPY attacks/ ./attacks/
COPY defenses/ ./defenses/
COPY eval/ ./eval/
COPY tests/ ./tests/
COPY main.py .
COPY inspect_memory.py .
COPY view_logs.py .

# Create volume mount directories
RUN mkdir -p /app/data /app/logs

VOLUME ["/app/data", "/app/logs"]

CMD ["python", "main.py", "--session-id", "docker_session"]
