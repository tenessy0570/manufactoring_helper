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

## Catalog

The worker refreshes the catalog at startup when stale and daily at 04:00 UTC.
It uses public ESI and EVE Ref endpoints; no API keys or SSO are needed.
`CATALOG_MAX_AGE_HOURS` defaults to 20. Failed tree/name downloads preserve the previous
catalog; missing metadata is retried on the next sync. Removed candidates become inactive.
The catalog contains candidate equipment, ammunition and drones, excluding capital branches;
manufacturability will be confirmed by the later blueprint/cost stages.

`GET /api/v1/catalog/items` supports combined filters:

- `search`: case-insensitive literal substring of the item name.
- `type_ids`, `exclude_type_ids`: include or exclude individual items.
- `categories`: root names, e.g. `Ship Equipment`, `Ammunition & Charges`, `Drones`.
- `market_group_ids`: exact market groups.
- `meta_group_ids`: meta groups, e.g. `1` for Tech I and `2` for Tech II.
- `is_rig`, `has_meta_group`, `is_active`: boolean filters; active items are the default.
- `limit` (1–1000), `offset`: pagination, ordered by type ID.

Repeat list parameters to select several values. Values within a filter use OR;
different filters use AND. Responses include `items`, `total`, `limit`, and `offset`.
Example: `/api/v1/catalog/items?meta_group_ids=2&is_rig=true&search=shield`.
Interactive API documentation is available at `/docs`.

Run `python scripts/esi_smoke.py` to probe public catalog endpoints without loading `.env`.
To additionally verify the migration and upserts on a disposable PostgreSQL 17 container,
run `RUN_POSTGRES_TESTS=1 pytest` (PowerShell: `$env:RUN_POSTGRES_TESTS='1'; pytest`).
