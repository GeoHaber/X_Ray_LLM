FROM python:3.12-slim AS base

LABEL maintainer="X-Ray LLM"
LABEL description="X-Ray code quality scanner"

WORKDIR /app

# Install OS-level deps for Rust scanner (optional)
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY xray/ xray/
COPY analyzers.py ui_server.py ui.html pyproject.toml ./

EXPOSE 8077

# Default: run the web UI
CMD ["python", "ui_server.py"]

# ------- CLI usage -------
# docker run --rm -v /path/to/code:/code xray-llm python -m xray /code --format json
