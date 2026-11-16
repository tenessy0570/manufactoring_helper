# EVE Manufacturing

Web service that finds the most profitable things to manufacture in EVE Online (Jita prices).
Replaces the standalone `eve_manufacturing_scan.py` script.

Only public ESI endpoints are used, so no SSO or app registration is needed.

## Run

```bash
cp .env.example .env   # fill in passwords
./redeploy.sh          # rebuilds images and recreates containers; volumes are kept
./redeploy.sh --pull   # same, but runs `git pull --ff-only` first
```

The site listens on `APP_PORT` (default 8000). Set `BASIC_AUTH_USERNAME` and
`BASIC_AUTH_PASSWORD` to protect it; `/health/*` stays open for healthchecks.

## Develop

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy && pytest
```

## Layout

```
app/core/      infrastructure: config, db, cache (memory + Redis), DI, repository base
app/domains/   one package per domain: models, tables, repository, service, router, providers
alembic/       migrations (run automatically on api start)
tests/         mirrors app/
```

A new domain adds its provider to `app/core/di/container.py` and its tables to
`app/core/orm_registry.py`.
