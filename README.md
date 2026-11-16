# EVE Manufacturing

EVE Online manufacturing profitability backend for Jita, Amarr, Dodixie, Rens and Hek.
Replaces the standalone script in `reference/eve_manufacturing_scan.py`.

Only public ESI and EVE Ref endpoints are used; no API keys, SSO or app registration are needed.

## Current state

Implemented: catalog sync, hub prices and demand, regional history/liquidity, manufacturing
profitability, persistent invention caching and saved calculation profiles. Migrations 0001-0007
create the required tables and an initial profile. The web interface is not implemented yet;
use the JSON API and interactive documentation at `/docs`. The root `/` has no application page.

Latest validation on Windows/Python 3.12: 253 tests passed, 1 optional PostgreSQL test skipped
in the default suite, 98.71% combined coverage. The PostgreSQL test passed separately, including
migrations, cache persistence and concurrent profile selection. Ruff, formatting and strict
mypy passed. Public ESI/EVE Ref smoke probes passed; a complete production Compose deployment
has not been validated end to end. These are recorded results, not checks run on every startup.

## Run

```bash
cp .env.example .env   # fill in passwords
./redeploy.sh          # rebuilds images and recreates containers; volumes are kept
./redeploy.sh --pull   # same, but runs `git pull --ff-only` first
```

The site listens on `APP_PORT` (default 8000). Set `BASIC_AUTH_USERNAME` and
`BASIC_AUTH_PASSWORD` to protect it; `/health/*` stays open for healthchecks.

On Windows, the equivalent initial commands are:

```powershell
Copy-Item .env.example .env
# Fill in credentials, then:
docker compose up -d --build --wait
```

Compose starts PostgreSQL 17, Redis 7, the API and four workers (main scheduler/prices,
history, manufacturing and invention). API startup applies migrations before workers start.
Initial data downloads are asynchronous; a healthy API can still return empty or pending data.
`/health/live` checks liveness; `/health/ready` checks database/Redis connectivity, not backfill progress.

Persistent data lives in named Docker volumes: `postgres_data` mounts at
`/var/lib/postgresql/data`, and `redis_data` at `/data` with AOF enabled. Container recreation
keeps both volumes; these are Docker-managed volumes, not folders in the repository.

Optional settings include `CATALOG_MAX_AGE_HOURS=20`, `MARKET_CACHE_SECONDS=300`,
`HISTORY_CACHE_SECONDS=86400`, `MANUFACTURING_CACHE_SECONDS=86400`,
`INVENTION_PLAN_TTL_SECONDS=604800`, and `INDUSTRY_MAX_CONCURRENCY=3`.

## Develop

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy && pytest --cov-fail-under=90
```

## Layout

```
app/core/      infrastructure: config, db, cache (memory + Redis), DI, repository base
app/domains/   one package per domain: models, tables, repository, service, router, providers
app/infrastructure/  public HTTP clients
app/workers/   ARQ schedulers and separate background queues
alembic/       migrations (run automatically on api start)
tests/         mirrors app/
tests/fixtures/  captured public data for reproducible calculations
reference/     original script/config; preserved as reference, excluded from Ruff
scripts/       optional public endpoint probes
```

A new domain adds its provider to `app/core/di/container.py` and its tables to
`app/core/orm_registry.py`.

## Catalog

The worker refreshes the catalog at startup when stale and daily at 04:00 UTC.
It uses public ESI and EVE Ref endpoints; no API keys or SSO are needed.
`CATALOG_MAX_AGE_HOURS` defaults to 20. Failed tree/name downloads preserve the previous
catalog; missing metadata is retried on the next sync. Removed candidates become inactive.
The catalog contains candidate equipment, ammunition and drones, excluding capital branches;
manufacturability is checked by the manufacturing recipe stage.

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

## Manufacturing opportunities

`GET /api/v1/manufacturing/opportunities` combines catalog items, manufacturing recipes,
station prices and regional liquidity. Material procurement and product sales independently
use `material_order_type=buy|sell` and `product_order_type=buy|sell`; both default to sell.
`hub_id` selects the product market; optional `material_hub_id` selects another procurement
hub. No external requests run during an opportunities query.

Calculations use base material quantities and base production time, **without ME/TE bonuses**.
Costs are divided by the real number of units produced in one run. Output includes materials,
costs per unit, profit per unit, margin and theoretical profit/day from one production slot.
For parity with the original script, margin is profit divided by material cost, multiplied
by 100; it is not profit divided by revenue. Slot/day profit does not guarantee daily sales.

`sales_tax` and `broker_fee` are percentages, both zero by default. Sales tax applies to product
revenue. Broker fees apply to material buy orders and product sell orders, not instant fills
against someone else's orders. Relisting is not modeled. `job_cost_per_run` optionally overrides
the cached EVE Ref installation estimate (which includes its SCC charge). That estimate uses
the source's NPC/default skill assumptions, not your actual system/structure/character.

The liquidity endpoint's catalog filters are available alongside `min_profit`, `max_profit`,
`min_margin`, `max_margin`, `min_profit_per_day` and `rank_by=profit_per_day|margin|profit`.
Ranking and filtering process all candidates before `limit`/`offset`. Missing prices or recipes
are excluded and counted, never treated as free inputs. `fresh_only` requires fresh history,
recipes and prices. T2 output explicitly marks invention as required and whether it was included.
Blueprint purchase/copy costs, hauling and custom facility bonuses are also not included.

Buy-side demand is reported separately from profit:

- `product_order_count`: all orders on the chosen side at the station.
- `orders_at_price`: orders at the quoted best price.
- `product_volume_at_price`: remaining units at that price.
- `full_runs_at_buy_price`: complete production runs that current best buy volume can absorb.
- `production_limit_units` and `profit_at_current_buy_price`: output and estimated profit
  from those complete runs, without assuming that demand replenishes.
- `demand_limited_profit_per_day`: per-slot daily production capped by that snapshot's volume.
- `demand_warnings`: a single buy order, a single order at the best price, insufficient volume
  for one run, or unknown counts on an older snapshot. Counts are orders, not unique players.

By default these rows remain visible with warnings. Optional `min_product_orders`,
`min_orders_at_price`, `min_product_volume`, `require_full_run_demand=true` and
`exclude_fragile_buy_demand=true` filter them. The latter two apply only to product buy-mode.
These are current quotes, not fill guarantees: orders may disappear before production ends.
In product buy-mode, the default daily-profit ranking and `min_profit_per_day` use the
demand-limited figure (`rank_profit_per_day`), so a high unit margin with tiny demand does not
dominate the ranking. `profit_per_day` remains the explicitly theoretical slot throughput.
Only best-price volume is covered, not lower-priced buy orders; no future replenishment is assumed.
Counts on pre-migration snapshots are null until the next price refresh, not a fabricated zero.

A separate `manufacturing-worker` fetches public EVE Ref recipes daily with three concurrent
requests and up to three attempts. Confirmed non-manufacturable products are cached; other
failures preserve previous recipes. `MANUFACTURING_CACHE_SECONDS` defaults to 86400.
`python scripts/manufacturing_smoke.py` captures one public response for reproducible tests.
The user interface remains a future stage.

## Invention cache

Invention runs in a separate `invention-worker` queue. PostgreSQL permanently stores the
source plans and requested price valuations; Redis and process memory accelerate cached reads.
Clearing Redis does not erase plans/results: the scheduler can recover work from PostgreSQL.
Page reads never call EVE Ref or perform the expensive invention lookup.

The public Industry Cost API resolves the source/invented blueprint for a T2 product, so no
full-network crawl of every blueprint is needed. Nine options (no decryptor plus eight types)
are cached together by product and assumed science/encryption levels. A failed or incomplete
download preserves the previous plan. `INVENTION_PLAN_TTL_SECONDS` defaults to seven days.
Redis locks share source work across hub/side requests; stable ARQ job IDs deduplicate requests.
Source calls use the shared bounded industry client (three concurrent requests by default).

Valuations are separate by hub, material buy/sell side, broker fee and skills. Price updates
reuse saved plans, without downloading the blueprints/options again. Their expiry is capped
by both source and market-price expiry; requested valuations refresh through the scheduler
every five minutes. Default backfill prepares Jita/sell with science 5 and encryption 4;
other settings are prepared on request. The initial backfill can take time.

API examples:

- `POST /api/v1/invention/2456/prepare?hub_id=amarr&order_type=buy&science_level=4`
  persists and queues one requested valuation; HTTP 202 does not mean the result is ready.
- `POST /api/v1/invention/prepare?hub_id=amarr&order_type=buy` schedules all active T2 catalog
  products for those settings, without doing the heavy calculations in the HTTP request.
- `GET /api/v1/invention/2456?hub_id=amarr&order_type=buy&science_level=4` reads cached status
  and alternatives. All settings must match the prepare request; broker fee defaults to 0.

States are `pending`, `ready`, `missing_prices`, `unsupported`, and `error`, with an independent
`stale` flag. An unrequested combination returns `request=null`. Failures retain old results
for inspection, expose only the error type, and retry up to three times. Partial price coverage
is marked `complete_pricing=false`; the best option is only the cheapest among priced options.
Unknown datacore/decryptor prices are never interpreted as free inputs.

Expected cost per manufactured unit is:
`(attempt materials + applicable buy-order broker fee + job estimate) / (success probability * runs per copy * units per manufacturing run)`.
Scaled upstream material/job quantities are normalized to one attempt before calculating.
This handles ammo/drone output quantities correctly. Skills are manual assumed common science
and encryption levels (0–5); no SSO or character access is used. Decryptor ME/TE is shown as
metadata, but does not modify manufacturing quantities, margin or throughput. Blueprint copy/
purchase costs and the player's actual facility/system bonuses remain outside this estimate.

Set `include_invention_cost=true` on `/api/v1/manufacturing/opportunities` to deduct a prepared
cost before profit/margin/demand-limited ranking. `invention_science_level` and
`invention_encryption_level` default to 5/4. The valuation follows `material_hub_id` (or `hub_id`),
`material_order_type` and `broker_fee`. Missing/failed T2 results are excluded and reported in
`missing_invention` and `invention_unavailable`, never charged zero. Stale cached results are
marked; `fresh_only=true` excludes them. Cost inclusion defaults to false.

`python scripts/invention_smoke.py` captures a public T2 response and validates all nine options.

## Saved profiles

Profiles persist every manufacturing query setting: product/procurement hubs, independent
buy/sell choices, optional taxes/fees, assumed invention skills and inclusion, liquidity and
profit/demand filters, sorting and page size. ME/TE fields are not accepted. Saved pagination
always starts at offset 0; browsing another page does not change the profile.

Migration 0007 creates a `Default` profile with sell/sell, zero trade taxes/fees and the same
defaults as a normal manufacturing query. The default selection is stored separately in one
singleton row. Writes lock that row on PostgreSQL so concurrent changes preserve one selection.
Creating or copying a profile does not change the default. Deleting the selected profile picks
the oldest remaining profile; deleting the final profile returns HTTP 409.

API:

- `GET /api/v1/profiles`, `POST /api/v1/profiles`.
- `GET /api/v1/profiles/default`, `GET /api/v1/profiles/{id}`.
- `PATCH /api/v1/profiles/{id}` changes `name` and/or `settings`. Omitted fields stay unchanged;
  a supplied `settings` object replaces the complete settings object, filling omitted settings
  with standard defaults. Null settings and unknown settings are rejected.
- `POST /api/v1/profiles/{id}/copy` with `{"name":"Another profile"}` copies settings independently.
- `PUT /api/v1/profiles/{id}/default`, `DELETE /api/v1/profiles/{id}`.
- `GET /api/v1/profiles/{id}/opportunities` or `/api/v1/profiles/default/opportunities` applies
  saved settings. Optional `limit`/`offset` override pagination for that response only.

Create example: `{"name":"Amarr buys","settings":{"hub_id":"amarr","product_order_type":"buy","require_full_run_demand":true}}`.
Profiles are identified by UUID; names may repeat. The existing `/manufacturing/opportunities`
endpoint remains a direct stateless query. Saving/applying a profile does not run remote source
calculations: matching invention valuations can be prepared through the existing invention API.
