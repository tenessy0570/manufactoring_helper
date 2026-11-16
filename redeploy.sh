#!/usr/bin/env bash
# Rebuilds images and recreates all containers. Named volumes (Postgres, Redis) are kept.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

WAIT_TIMEOUT_SECONDS=120

if [[ "${1:-}" == "--pull" ]]; then
    git pull --ff-only
fi

if [[ ! -f .env ]]; then
    echo "error: .env not found. Copy .env.example to .env and fill in the values." >&2
    exit 1
fi

if ! docker compose up -d --build --force-recreate --remove-orphans \
    --wait --wait-timeout "${WAIT_TIMEOUT_SECONDS}"; then
    echo "error: services did not become healthy within ${WAIT_TIMEOUT_SECONDS}s" >&2
    docker compose ps >&2
    docker compose logs --tail=50 >&2
    exit 1
fi

docker image prune -f >/dev/null
docker compose ps
