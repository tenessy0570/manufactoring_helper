"""Probe a public manufacturing calculation and save a reproducible test fixture."""

import asyncio
import json
from pathlib import Path

import httpx


async def main() -> None:
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "eve-manufacturing"}) as http:
        response = await http.get(
            "https://api.everef.net/v1/industry/cost",
            params={
                "product_id": 2454,
                "me": 0,
                "te": 0,
                "runs": 1,
                "material_prices": "FUZZWORK_JITA_SELL_MIN",
            },
        )
        response.raise_for_status()
        data = response.json()
        path = Path("tests/fixtures/manufacturing.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_text, json.dumps(data, indent=2), encoding="utf-8")
        print(json.dumps(data.get("manufacturing"), indent=2))
        unsupported = await http.get(
            "https://api.everef.net/v1/industry/cost", params={"product_id": 34}
        )
        print(f"Unsupported product: {unsupported.status_code} {unsupported.text[:250]}")


if __name__ == "__main__":
    asyncio.run(main())
