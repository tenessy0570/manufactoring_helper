FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY pyproject.toml ./
COPY app ./app
RUN pip install -e .

COPY alembic.ini ./
COPY alembic ./alembic
COPY docker/start-api.sh /usr/local/bin/start-api
RUN chmod +x /usr/local/bin/start-api \
    && useradd --system --no-create-home appuser

USER appuser
EXPOSE 8000
CMD ["start-api"]
