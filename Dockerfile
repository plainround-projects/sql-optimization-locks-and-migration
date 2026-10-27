# The command-line programs as an image. Nothing here serves traffic; the health command is the image's check.
# Run against a PostgreSQL the container can reach, for example:
#   docker run --rm --network host -e PGPASSWORD=... sql-optimization-locks-and-migration:dev locks-lab-run
FROM python:3.13.1-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.lock ./
RUN pip install --require-hashes -r requirements.lock

COPY pyproject.toml README.md ./
COPY src ./src
COPY sql ./sql
RUN pip install --no-deps .

RUN useradd --system --uid 10001 --no-create-home app
USER app
ENV LAB_SQL_DIR=/app/sql

HEALTHCHECK --interval=30s --timeout=20s --retries=3 CMD ["locks-lab-health"]
CMD ["locks-lab-health"]
