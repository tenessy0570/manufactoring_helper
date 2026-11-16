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

## Market prices

`GET /api/v1/market/hubs` lists the supported public NPC hubs: Jita, Amarr, Dodixie,
Rens and Hek. `GET /api/v1/market/prices?hub_id=amarr` selects a hub; Jita is the default.
Each hub has its own snapshot and freshness timestamps. Structure markets are not included.

The worker checks all five hubs every five minutes and at startup, skipping snapshots until
their ESI `Expires` time. `MARKET_CACHE_SECONDS` (default 300) caps the refresh interval and
provides a fallback for missing or malformed expiration headers. A failure in one hub does
not stop the remaining hubs. Full regional order books are read page by page; only compact
best-price summaries for the chosen station are retained. Successful downloads replace that
hub's prices in one transaction, including removal of prices whose orders disappeared.
Failed pages or a changing page count preserve the previous snapshot. ESI does not supply a
transactional snapshot across pages, so orders can still change during a scan.

Prices use Decimal and are returned as JSON strings. Buy price is the highest buy order at
the station; sell price is the lowest sell order. Volumes sum orders at those exact best prices,
not the full order book or daily traded volume. Ranged buy orders originating elsewhere are
excluded. `spread` is sell minus buy, before fees; it is not manufacturing profit.

Available combined filters:

- `type_ids`, `exclude_type_ids` (repeat for multiple IDs).
- `min_buy_price`, `max_buy_price`, `min_sell_price`, `max_sell_price`.
- `min_spread`, `max_spread` (ISK).
- `min_buy_volume`, `min_sell_volume` (units at the best price).
- `has_buy`, `has_sell`, `fresh_only`.
- `limit`, `offset`, ordered by type ID.

Responses contain hub details, sync state, a `stale` flag, `items`, `total`, `limit` and `offset`.
Prices remain visible when stale unless `fresh_only=true` is requested. An unsynced hub returns
an empty page with `state=null` and `stale=true`. The catalog filters remain available separately
at `/api/v1/catalog/items`; catalog metadata and market history are not part of this endpoint.

## Regional history and liquidity

`GET /api/v1/market/history/34?hub_id=amarr&days=30` returns daily history for the hub's
**region**, not its station. Responses include `scope=region`, region/hub information,
refresh state and a stale flag. Current-day data is excluded.

`GET /api/v1/market/liquidity?hub_id=jita&days=30&min_daily_isk_volume=500000000`
lists active catalog items with liquidity metrics. The period is 1–365 completed UTC days,
ending yesterday. Daily units are `sum(volume) / days`; estimated daily ISK turnover is
`sum(average price * volume) / days`. The divisor is the full calendar period, so gaps do
not inflate averages. `data_days` reports how many daily records are available. No records
in the period means null metrics, not zero; known zero-volume records produce zero.
This is an estimate from ESI daily statistics, not an exact station trading ledger.

Combined filters include `type_ids`, `exclude_type_ids`, `search`, `categories`,
`meta_group_ids`, `is_rig`, `has_history`, `fresh_only`, `min_daily_isk_volume`,
`max_daily_isk_volume`, `min_daily_units`, `max_daily_units`, `limit` and `offset`.
List parameters can be repeated. Responses include the date range, total count and metrics.
Minimum filters exclude unknown metrics even when the threshold is zero.

History downloads run in a separate `history-worker` service and Redis queue so the initial
backfill does not delay current-price jobs. The main worker schedules active catalog items
for all five regions at startup and hourly; daily deterministic job IDs prevent duplicate
batches. The history worker uses at most ten concurrent item requests, skips fresh items,
and retries failed batches up to three times. Each item is committed independently, so
failures preserve previous history and successful items do not need downloading again.
Successful empty responses are cached too. `HISTORY_CACHE_SECONDS` defaults to 86400 and
caps/falls back for the ESI expiration header. The first full backfill can take time.

The next profitability stage will support independent material/product buy/sell choices,
both defaulting to **sell**. Sales tax and broker fees will default to **0%** with optional
user-entered percentages. These calculation/profile controls are not implemented yet.
