# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -c "import tomllib; from pathlib import Path; data = tomllib.loads(Path('pyproject.toml').read_text()); Path('/tmp/build-requirements.txt').write_text('\n'.join(data['build-system']['requires'] + ['wheel'] + data['project']['dependencies']))" \
    && pip install -r /tmp/build-requirements.txt

COPY docker/start-api.sh /usr/local/bin/start-api
RUN chmod +x /usr/local/bin/start-api \
    && useradd --system --no-create-home appuser

COPY app ./app
RUN pip install --no-index --no-deps --no-build-isolation -e .

COPY alembic.ini ./
COPY alembic ./alembic

USER appuser
EXPOSE 8000
CMD ["start-api"]
