FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY lizard ./lizard
RUN pip install --no-cache-dir ".[gpu]"

FROM base AS egg
CMD ["lizard-egg"]

FROM base AS nest
CMD ["lizard-nest"]
