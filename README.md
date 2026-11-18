# EVE Manufacturing

EVE Online manufacturing profitability backend for Jita, Amarr, Dodixie, Rens and Hek.
Replaces the standalone script in `reference/eve_manufacturing_scan.py`.

Only public ESI and EVE Ref endpoints are used; no API keys, SSO or app registration are needed.

## Current state

Implemented: catalog sync, hub prices and demand, regional history/liquidity, manufacturing
profitability, persistent invention caching, saved calculation profiles and private production
history. Migrations 0001-0011
create the required tables and an initial profile. The English web interface is available at `/`,
with a unified filter panel, browser profiles and item details. Interactive API documentation
is available at `/docs`. The shared navigation groups workspace tools and account links,
highlights the active page and collapses into an accessible menu on mobile.

Latest validation on Windows/Python 3.12: 338 tests passed, 1 optional PostgreSQL test skipped
in the default suite, 97.17% combined coverage. The PostgreSQL test passed separately, including
migrations, cache persistence, concurrent profile selection and concurrent production income. Ruff, formatting and strict
mypy passed. Public ESI/EVE Ref smoke probes passed; a complete production Compose deployment
has not been validated end to end. These are recorded results, not checks run on every startup.

## Run

```bash
cp .env.example .env   # fill in passwords
./redeploy.sh          # rebuilds images and recreates containers; volumes are kept
./redeploy.sh --pull   # same, but runs `git pull --ff-only` first
```

The site listens on `APP_PORT` (default 8000). All tools, data APIs, demo pages and API docs
require a user login. Local accounts replace the former optional HTTP Basic Auth; legacy
`BASIC_AUTH_*` values do not create accounts or bypass the login screen.

Create the first superuser from the server terminal (password is prompted without echo):

```bash
docker compose exec api python -m app.domains.accounts.manage --username admin
```

Then open `/login`. Superusers manage users at `/admin`: create accounts/superusers,
disable/enable access and reset passwords. Users have `/account` with logout and password
change. Public self-registration is unavailable. Passwords must contain 12-128 characters;
usernames are case-insensitive ASCII letters/digits plus dot, underscore or hyphen (3-32).
Changing/resetting a password or disabling an account revokes its sessions. You cannot disable
your own account. Production history belongs to each user; existing server calculation profiles
remain shared.

Migration 0010 stores users and hashed opaque session tokens in PostgreSQL. Session cookies
are HttpOnly, SameSite=Lax, Secure on HTTPS, expire after 14 days. Passwords use salted scrypt
(32768/8/3), calculated outside the event loop. Login attempts are limited in Redis over
15 minutes (10 per username/address, 50 per address). Serve public deployments over HTTPS.
Mutating API requests, including login/logout, require `X-Requested-With: XMLHttpRequest`;
foreign Origin headers are rejected. No CORS access is enabled. Only `/login`, login API,
static assets, and exact `/health/live` and `/health/ready` are public. Data coverage is private.
There is no ESI SSO or character access involved.

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

## Production history

Open `/production-history` after login. Create a batch by product/blueprint name; planned finished
units and comments are optional. A new batch has no expenses. Add invention, materials and
manufacturing expenses independently as work progresses, and increase planned units when extending
the batch. Changing units does not rewrite previously saved expenses.

Record each partial sale using **Income from sale ? Received (ISK) ? Add income**. Received sums
accumulate; quantities sold are not required, so remaining stock is not inferred. Entries can be
edited/deleted, and batches marked completed. Cash balance is received income minus recorded
expenses; return on costs uses total recorded expenses as denominator. Neither values unsold stock
nor assumes unrecorded expenses are zero. An absent category shows **Not recorded**; an explicit
zero is retained. Amounts accept up to two decimal places.

**Estimate from saved market data ? Estimate & fill amount** fills an editable amount without
saving it. Choose the finished units for this particular expense (including additional batches).
Materials use whole runs, output units/run, ME 0 and saved hub buy/sell prices; procurement buy
broker fees are optional. Manufacturing uses the saved base/SCC charge plus optional EIV-based
facility tax and system cost index. Invention reuses the shared source plans with skills II/II/II
and the cheapest total expected datacore/decryptor budget for the batch, excluding T1 BPC prices.
Missing data returns an actionable message; stale data is flagged. Estimates trigger no external
fetches or new invention jobs. Saved ledger amounts do not change when market prices refresh.

Migration 0011 stores private ledgers in PostgreSQL. `/api/v1/productions` exposes paginated
GET/POST, `/{id}` GET/PUT/DELETE, `/{id}/entries` POST, `/{id}/entries/{entry_id}` PUT/DELETE,
and `/{id}/estimate` POST. Ownership is taken from the session, never accepted from input;
foreign records return 404 even to superusers. Parent row locks serialize ledger changes to retain
concurrent additions. Production pages and APIs use the existing session and CSRF protections.

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
Interactive API documentation is available at `/docs`. The shared navigation groups workspace tools and account links,
highlights the active page and collapses into an accessible menu on mobile.

Run `python scripts/esi_smoke.py` to probe public catalog endpoints without loading `.env`.
To additionally verify the migration and upserts on a disposable PostgreSQL 17 container,
run `RUN_POSTGRES_TESTS=1 pytest` (PowerShell: `$env:RUN_POSTGRES_TESTS='1'; pytest`).

## Market prices

`GET /api/v1/market/hubs` lists the supported public NPC hubs: Jita, Amarr, Dodixie,
Rens and Hek. `GET /api/v1/market/prices?hub_id=amarr` selects a hub; Jita is the default.
Each hub has its own snapshot and freshness timestamps. Structure markets are not included.

The worker checks all five hubs hourly and at startup, skipping snapshots until
their ESI `Expires` time. `MARKET_CACHE_SECONDS` (default 300) caps the refresh interval and
provides a fallback for missing or malformed expiration headers. A failure in one hub does
not stop the remaining hubs. Full regional order books are read page by page; best-price summaries and aggregated buy-price levels for the chosen station are retained;
individual regional orders are not stored. Successful downloads replace that
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

Five independent percentage settings default to zero (blank/null also means zero):
`buy_broker_fee`, `sell_broker_fee`, `sales_tax`, `facility_tax`, `system_cost_index`.
Buy broker applies only to material BUY orders, sell broker only to product SELL orders;
sales tax applies to either product sale type. Relisting is not modeled. Legacy `broker_fee`
remains a shorthand for both broker rates when the separate values are omitted; explicit values,
including zero, win. Old browser and server profiles retain their previous broker settings.

Facility tax and system cost index apply ONLY to manufacturing, using the recipe's EVE Ref
estimated item value (EIV), not the market material cost or product revenue:
`installation/run = cached base/SCC charge + EIV * (facility_tax + system_cost_index) / 100`.
SCC surcharge remains included in the base charge even when all five user rates are zero,
as explicitly requested. `job_cost_per_run` overrides that BASE charge; the entered EIV-based
charges still apply. Structure bonuses, alpha tax overrides and automatic system lookup are
not modeled. Invention estimates are explicitly tax-free: only datacores/decryptors, no broker
fees or installation/SCC charges. None of the five rates changes its cache key or queues work.

All charges reduce net profit and therefore margin, profit/day and price-weighted demand profit.
The item card exposes EIV per unit, base/SCC, facility tax and system index charge separately.
Recipes persist EIV in their existing JSON payload; no database column change is needed.
Legacy recipes are refreshed once for this missing metadata even if their normal TTL has not
expired. With nonzero industry rates, missing EIV excludes the item and increments
`missing_job_costs`; zero-rate calculations remain available. The manufacturing queue ID has
an EIV revision so completed pre-feature jobs do not suppress this backfill.

The liquidity endpoint's catalog filters are available alongside `min_profit`, `max_profit`,
`min_margin`, `max_margin`, `min_profit_per_day` and `rank_by=profit_per_day|margin|profit|demand_profit`.
Ranking and filtering process all candidates before `limit`/`offset`. Missing prices or recipes
are excluded and counted, never treated as free inputs. `fresh_only` requires fresh history,
recipes and prices. T2 output explicitly marks invention as required and whether it was included.
Blueprint purchase/copy costs, hauling and custom facility bonuses are also not included.

Buy-side demand is reported separately from profit:

- `product_order_count`: buy orders inside the selected price range, or all sell orders.
- `orders_at_price`: orders at the quoted best price.
- `product_volume_at_price`: remaining units at that price.
- `buy_demand_tolerance_pct`: maximum drop below the best buy price, default 5%; blank/null
  uses 5%, and 0 means best price only. Valid range: 0-100%.
- `buy_demand_volume`, `buy_demand_min_price`, `buy_demand_average_price`: eligible volume,
  lowest included price and volume-weighted sale price for complete-run output.
- `full_runs_at_buy_price`: legacy field name for complete runs covered by the selected buy range.
- `production_limit_units` and `profit_at_current_buy_price`: output and estimated profit
  from those complete runs using their actual price levels, without assuming replenishment.
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
Buy demand includes price levels within the selected percentage below the best price. Profit
is integrated from the highest price downward with the actual sales tax and per-unit build cost,
not calculated by multiplying all units by the best-price margin. No future replenishment is assumed.
Counts on pre-migration snapshots are null until the next price refresh, not a fabricated zero.

A separate `manufacturing-worker` fetches public EVE Ref recipes daily with three concurrent
requests and up to three attempts. Confirmed non-manufacturable products are cached; other
failures preserve previous recipes. `MANUFACTURING_CACHE_SECONDS` defaults to 86400.
`python scripts/manufacturing_smoke.py` captures one public response for reproducible tests.
The English web interface is available at `/`.

## Invention cache

Invention runs in a separate `invention-worker` queue. PostgreSQL permanently stores the
source plans and requested price valuations; Redis and process memory accelerate cached reads.
Clearing Redis does not erase plans/results: the scheduler can recover work from PostgreSQL.
Page reads never call EVE Ref or perform the expensive invention lookup.

The public Industry Cost API resolves the source/invented blueprint for a T2 product, so no
full-network crawl of every blueprint is needed. Nine options (no decryptor plus eight types)
are cached together by product with fixed science 5/encryption 4 assumptions. A failed or incomplete
download preserves the previous plan. `INVENTION_PLAN_TTL_SECONDS` defaults to seven days.
Redis locks share source work across hub/side requests; stable ARQ job IDs deduplicate requests.
Source calls use the shared bounded industry client (three concurrent requests by default).

Valuations are separate only by product, hub and material buy/sell side; tax rates are excluded. Price updates
reuse saved plans, without downloading the blueprints/options again. Their expiry is capped
by the daily valuation boundary at 12:30 UTC, independently of source/price cache expiry; requested valuations refresh through the scheduler
daily at 12:30 UTC and at startup. Default backfill prepares Jita/sell with science 5 and encryption 4;
other settings are prepared on request. The initial backfill can take time.

API examples:

- `POST /api/v1/invention/2456/prepare?hub_id=amarr&order_type=buy`
  persists and queues one requested valuation; HTTP 202 does not mean the result is ready.
- `POST /api/v1/invention/prepare?hub_id=amarr&order_type=buy` schedules all active T2 catalog
  products for those settings, without doing the heavy calculations in the HTTP request.
- `GET /api/v1/invention/2456?hub_id=amarr&order_type=buy` reads cached status
  and alternatives. Hub and material price side must match the prepare request. Legacy broker-fee inputs are ignored.

States are `pending`, `ready`, `missing_prices`, `unsupported`, and `error`, with an independent
`stale` flag. An unrequested combination returns `request=null`. Failures retain old results
for inspection, expose only the error type, and retry up to three times. Partial price coverage
is marked `complete_pricing=false`; the best option is only the cheapest among priced options.
Unknown datacore/decryptor prices are never interpreted as free inputs.

Expected cost per manufactured unit is:
`attempt materials / (success probability * runs per copy * units per manufacturing run)`.
The estimate includes datacores/decryptors and expected failed attempts, excluding all taxes
and broker fees. Manufacturing SCC is still charged separately as described above.
Scaled upstream material/job quantities are normalized to one attempt before calculating.
This handles ammo/drone output quantities correctly. Skills are fixed to science 5/encryption 4;
no user skill variants, SSO or character access are used. Decryptor ME/TE is shown as
metadata, but does not modify manufacturing quantities, margin or throughput. Blueprint copy/
purchase costs and the player's actual facility/system bonuses remain outside this estimate.

Set `include_invention_cost=true` on `/api/v1/manufacturing/opportunities` to deduct a prepared
cost before profit/margin/demand-limited ranking. Legacy skill settings are ignored. The valuation follows `material_hub_id` (or `hub_id`),
`material_order_type`; it is shared across all tax settings. Missing/failed T2 results are excluded and reported in
`missing_invention` and `invention_unavailable`, never charged zero. Stale cached results are
marked; `fresh_only=true` excludes them. Cost inclusion defaults to false.

`python scripts/invention_smoke.py` captures a public T2 response and validates all nine options.

## Saved profiles

The first English interface is available at `/` on the application server. It includes an
opportunities table, filters, hub and buy/sell controls, saved profile selection, pagination,
material details, demand limits and cached invention preparation. Profile editing and regional
history charts are not yet exposed in the interface.

To preview the layout without running PostgreSQL, Redis or workers:

```powershell
.venv\Scripts\python.exe scripts/preview_ui.py
```

Open `http://127.0.0.1:8765/?demo=1`. This mode uses labeled sample data; it is intended for
layout inspection, not validation of live prices or every server-side filter. Live data requires
the regular application server and populated database. The standalone preview has no market API.

Frontend assets are bundled locally. To rebuild the stylesheet with Tailwind CSS 3.4.17:

```text
tailwindcss -i frontend/input.css -o app/web/static/app.css --minify
```

The standalone Tailwind executable can be used without Node.js. HTMX 2.0.4 and Alpine.js 3.14.9
are pinned in `app/web/static/vendor/`; item icons use the public EVE image service.

Profiles persist every manufacturing query setting: product/procurement hubs, independent
buy/sell choices, optional taxes/fees, invention inclusion, liquidity and
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


## Synchronization recovery (2026-11-17)

Market pages are fetched in batches of five. A changing page count restarts the whole snapshot up to three times; exhausted attempts preserve the previous snapshot. Only ESI history 404 with the exact `Type not found!` response is cached as empty history; other errors still fail. Products with multiple source blueprints are skipped with a warning rather than marked non-manufacturable or assigned an arbitrary recipe. Explicit blueprint selection remains unsupported. Validation: 265 passed, 1 skipped; coverage 98.52%; Ruff and mypy passed.


## Mass production candidates

Manufacturing opportunities are restricted to meta groups 1 (Tech I, including named/meta variants) and 2 (Tech II), matching the original scanner. User filters and saved profiles can narrow this selection but cannot expand it. Other groups and unknown metadata are excluded even when a cached recipe exists. A valid manufacturing recipe is still required; not every named/meta module is buildable. History and recipe scheduling use the same group restriction. The catalog remains available for metadata inspection.


## UI settings and rigs correction (2026-11-17)

Browser filters, hub/order sides, taxes, profile snapshot and expanded filters persist in localStorage (versioned, separate live/demo keys); reload starts at page one. Corrupt or disabled storage does not block filtering. The market selector now includes Rigs branches under the separate Ship and Module Modifications root, retaining full paths and excluding capital rigs and unrelated branches. Confirmed public ESI path for type 31796: 955 -> 1111 -> 965 -> 1235. Existing Docker catalog had no rigs at all. Deployment must be followed by forced catalog sync and history/recipe/invention scheduling; a restart alone may skip the fresh catalog for 20 hours. Python checks: 275 passed, 1 skipped, coverage 98.41%; Ruff/format/mypy passed. Hidden Edge JS smoke check passed for filter restore, malformed storage and demo separation. Not committed or deployed.


## Browser profiles and unified categories (2026-11-17)

The UI has one item-category selector: All categories, Rigs, Ammo, Drones, Modules. Rigs maps to is_rig=true without a category restriction; Modules maps to Ship Equipment and is_rig=false. Existing browser settings with separate category/rig controls are migrated on restore. Save as profile stores a named snapshot of current visible and hidden settings in localStorage, independent of server profiles; duplicate browser names are rejected. Browser profiles appear with a browser label and survive reloads on the same origin/browser; clearing site storage removes them. Settings restore before profile loading, and default server profiles do not overwrite restored settings. Applying filters and pagehide explicitly save current state. Reactive server profile copying no longer uses structuredClone. Real browser reload/profile apply/category mapping checks passed. Forced catalog sync completed in Docker: 237 T1 rigs, 237 T2 rigs and 474 rig recipes; 415 history batches and 83 recipe batches queued.


## Interface workflow

All controls live in one filter form, grouped into items, market prices, profit/demand, calculation assumptions and result ordering. Show results applies the current filters and reloads saved results; unsaved filter edits are shown explicitly and do not relabel existing results. The duplicate top-level reload button was removed; source refresh remains a background task. Pagination is disabled until edited filters are applied. Browser profiles can be created, updated and deleted with confirmation; deleting a profile keeps the current filters. The item dialog supports Escape, keyboard focus containment and focus restoration. Mobile layouts keep horizontal scrolling inside the table.

Frontend regression checks (isolated Edge/Chromium, no live database):

```powershell
.venv\Scripts\python.exe scripts/check_frontend.py
```

Pass `--browser` to specify another Chromium executable. The runner starts and stops its own preview and browser, uses a temporary browser profile, checks the main workflow and saves desktop/mobile screenshots in the temporary directory.

Legacy science/encryption values in API requests, queued jobs and saved profiles are ignored; they no longer create separate source plans or valuation keys. Existing default 5/4 cache keys are preserved.


Refresh schedule: market orders hourly at :00 UTC; regional-history planning daily at 12:15 UTC (19:15 Tomsk); invention valuation planning daily at 12:30 UTC (19:30 Tomsk). Startup also checks stale data. A valuation is retained until the next daily refresh boundary; hourly market refreshes do not automatically reprice it. Explicit preparation of a new setting combination remains available. ESI expiry still marks market snapshots stale; polling less often does not change ESI freshness.

Daily valuation expiry is aligned to 12:30 UTC, rather than job-finish time plus 24 hours: otherwise queue delay can make the next daily planner skip a still-fresh result for another full day. Existing valuation expiry timestamps must be aligned during deployment. Latest checks: 314 passed, 1 skipped; Ruff, format and mypy passed.


## Readable item details

Materials show English inventory names and icons, quantities and readable ISK prices per production run. Per-unit build costs, purchase broker fees, sales tax and sale broker fees are listed separately. GET /api/v1/catalog/names accepts repeated positive type_ids (1-1000 IDs), resolves names in one public ESI request and caches complete batches for seven days through Redis/RAM. Incomplete lookups are returned with missing_type_ids and are not cached, so retry can recover missing names. Name-service failures do not block the financial breakdown.

The results help explains margin, per-slot daily profit, regional turnover and stale inputs. Buy-order warnings and invention states use plain English. Missing-input notices distinguish recipes, prices and invention; a separate button queues invention preparation for the applied material market and pricing choice.

Monetary displays use at most two decimal places without trailing zeroes. This rounding affects display only; backend Decimal calculations and stored values retain their precision.


Invention panel layout/feedback: alternatives use aligned columns with decryptor, per-attempt success chance and estimated ISK per finished unit; the cheapest priced alternative is marked. Mobile rows become labeled cards and the dialog cannot grow beyond the viewport. Check status shows a loading state, response feedback and a last-checked timestamp; saved/expiry timestamps are displayed in the browser timezone. Prepare calculation consumes the POST response and distinguishes queued work, cached-ready reuse and unsupported routes. Fresh ready results show a disabled Already prepared action. API logs confirmed the prior buttons sent GET 200 and POST 202; lack of visible feedback and cache reuse made them appear inert. Added browser checks for progress, queued/cached responses and nine-option mobile layout. No financial formulas or refresh cadence changed. Not committed.


Profit on demand is shown directly in the table with units and full-run counts. The selected price range defaults to 5% below the best buy price; 0% means best price only. Profit sums revenue at the actual included prices, less taxes and production costs, excluding residual volume smaller than one run and orders outside the range. Sell pricing has no executable demand and displays Buy pricing only. rank_by=demand_profit sorts total profit descending before pagination, with unavailable values last and type ID as tie-breaker. The threshold and sort selection persist in browser/server profiles.

Migration 0008 adds nullable buy_levels JSON to market snapshots. Old snapshots have unknown depth and conservatively use best-price volume only, with an explicit UI notice, until the next successful market refresh. New snapshots store volume and order count per station buy price, not individual orders. Changing the threshold reads these saved levels without issuing ESI requests or new invention jobs.

The demand column also estimates sequential manufacturing time on one line using Industry V and Advanced Industry III: full runs ? base seconds per run ? 0.80 ? 0.91. The tooltip and item details state these assumptions. This display-only estimate excludes TE, facilities, specialist skills, invention, copying and manufacturing input materials; it does not change margin or daily-profit calculations.

Migration 0009 merges historical broker-fee invention variants into one valuation per
product/hub/price side. It removes embedded broker fees and installation charges from the
saved attempt costs, recomputes unit costs/best decryptor locally, and preserves the selected
ready result's timestamps and expiry. No ESI/EVE Ref lookup or plan regeneration is needed.
Source-plan keys and the former zero-fee valuation keys remain compatible. The migration's
downgrade retains the canonical estimates rather than recreating discarded fee variants.
Changing a user's tax rates never schedules invention. Source plans remain cached seven days;
material-price valuations still refresh daily at 12:30 UTC.

Production lines setting: production_lines, integer 1..1000, defaults to 1 (blank/null also 1). Saved in browser/server profiles. Demand completion time uses ceil(full runs / lines) * adjusted seconds per run, preserving whole runs; applied settings determine displayed time. Financial profit and daily ranking remain unchanged. Committed in 34bf018.

Table Columns chooser: seven optional metric/data columns with checkboxes, all visible by default. Item identity remains visible. hiddenColumns stored in versioned browser settings separately from calculation/profile filters; Show all columns resets visibility. No API calls for toggles. Browser verified matching hidden headers/cells and storage restoration. Committed in 34bf018.

Columns control now sits at the top-right edge of the table, opening a compact checkbox popover. Outside click/Escape closes it; Escape restores button focus. Committed in 34bf018 after the menu placement update.

Background data coverage is available above the table and at GET /health/data-progress?hub=jita.
It reports persisted catalog/recipe/history coverage, market snapshot size/time, and T2 invention
status counts (sell-priced inputs). It refreshes every 30 seconds while the page is visible and
on hub/result changes; manual Refresh status is available. Counts are saved coverage, not a claim
that a worker is currently running. This read-only endpoint performs no upstream downloads.

Market snapshot coverage shows elapsed hours/minutes instead of absolute date; exact timestamp remains in tooltip. Elapsed display updates on the 30-second visible-page tick.

Item details include SVG charts of saved regional daily average price and traded volume, using the applied hub and history period. UTC dates, independent price/volume scales, pointer inspection and an expandable exact-values table are included. Missing dates break price lines; empty/error/stale states are explicit and do not block costs. No new dependencies or upstream requests; the existing saved-history API is used.

History charts now share one plot: muted blue volume bars behind a green average-price line, left ISK axis/right units axis, matching legend, shared dates and day inspection. Exact-values table retained.

Owner cancelled remaining blueprint-selection and server-profile UI stages. Only Docker build optimization remains in scope: dependencies extracted directly from pyproject.toml into an early BuildKit-cached pip layer; app copied afterward, installed offline with no dependency resolution/build isolation. Code/UI edits reuse dependency layer; pyproject changes invalidate it. First build populates cache.

Docker optimization verified: normal compose built all five app images; source-only app.js change rebuilt a separate verification image in 6.8 seconds with dependency step CACHED and no downloads. Temporary source modification restored byte-for-byte. All five application containers recreated and healthy. Other pending feature stages cancelled by owner. Changes uncommitted.

New invention shopping planner: /invention-shopping, navigation from Opportunities.
Search cached T2 products by product/blueprint name (Blueprint suffix removed), select target,
enter finished-unit count and price hub (Jita default). GET /api/v1/invention/shopping/{type_id}
accepts units=1..1e9 and hub_id. Reuses canonical weekly source plan and cached hub sell prices;
explicit Prepare uses existing deduplicated invention queue, no per-skill source variants.
Planner-only skills are both science II and encryption II; existing opportunity valuation remains
science V/encryption IV. Chance scales cached probability by 71/86 (CCP Phoebe formula:
https://www.eveonline.com/fr/news/view/patch-notes-for-phoebe).
Manufacturing runs=ceil(desired units/units per run); successful BPCs=ceil(runs/BPC runs);
attempt budget=ceil(successful BPCs/chance). Materials and T1 BPC licensed-run requirement scale
by whole attempts, NOT number of BPC physical copies. Output capacity can exceed desired units,
especially ammunition. This is rounded-up expected consumption, not a probability guarantee.
Automatic best decryptor minimizes total datacore+decryptor shopping budget for the requested
batch, including chance/runs/output/rounding (NOT lowest decryptor purchase price). T1 BPC costs,
manufacturing materials, taxes and fees excluded. Missing prices exclude alternatives from best;
partial/no pricing explicit. Alternative comparison shown. Names resolve via cached names API.
Empty/unsupported/stale/error states, explicit preparation/check status; no new upstream reads
for calculations. New feature uncommitted; previous committed checkpoint 7928ac5.

Shopping UI condensed: four summary cards (budget, attempts/chance, T2 copies/runs, capacity/request), best-decryptor header, item icons including T1 BPC/datacores/decryptor. Long assumptions under Calculation details; concise visible uncertainty/BPC-cost note preserved.

Shopping blueprint search now uses an inline autocomplete listbox, replacing separate select. Mouse/arrow/Enter selection, Escape/outside/Tab dismissal, immediate invalidation and stale-search guards. BPC images use image-server /bpc variant (blueprint /icon returned400, /bpc returned200 in live probe).

Invention shopping Copy buy list exports supply material names plus tab-separated whole quantities, newline-separated for EVE Multibuy paste. T1 BPC licensed runs excluded. Copy disabled until all names resolve; clipboard fallback/manual textarea available.

Invention chance now accompanied by runs per successful T2 BPC in shopping summary/alternatives and opportunity detail alternatives. Shopping response exposes runs_per_copy and units_per_run from shared source plan.
