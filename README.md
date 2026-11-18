# EVE Manufacturing

A web app for planning manufacturing in EVE Online. Compare profitability and market demand
across five trade hubs, calculate invention shopping lists, and track personal production
expenses and income from partial sales. Uses public ESI and EVE Ref data; no EVE API keys needed.

## Run

Requires Docker with Docker Compose.

1. Copy `.env.example` to `.env` and configure the database and Redis credentials:

   ```bash
   cp .env.example .env
   ```

   On Windows PowerShell, use `Copy-Item .env.example .env` instead.

2. Build and start the project:

   ```bash
   docker compose up -d --build --wait
   ```

3. Create the first administrator and enter a password of at least 12 characters when prompted:

   ```bash
   docker compose exec api python -m app.domains.accounts.manage --username admin
   ```

4. Open [localhost:8000](http://localhost:8000) and log in. Administrators create additional
   accounts at `/admin`.

Market data loads in the background; initial results may take time to appear.
The port can be changed with `APP_PORT`. Database and cache data persist in Docker volumes.

To rebuild after code changes, run `docker compose up -d --build --wait` again.
