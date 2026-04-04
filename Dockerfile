FROM python:3.13-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies (layer-cached separately from source code)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Activate the venv for all subsequent RUN/CMD steps
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy application source
COPY . .

EXPOSE 5000

CMD ["python", "run.py"]
