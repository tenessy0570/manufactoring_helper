"""Probe a few public catalog endpoints without loading .env or using credentials."""

import asyncio

import httpx


async def main() -> None:
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "eve-manufacturing"}) as http:
        for url in (
            "https://esi.evetech.net/markets/groups/",
            "https://esi.evetech.net/markets/groups/4/",
            "https://ref-data.everef.net/types/587",
        ):
            response = await http.get(url)
            print(f"{response.status_code} {url}")
            for header in ("X-Ratelimit-Remaining", "X-Esi-Error-Limit-Remain", "Retry-After"):
                if header in response.headers:
                    print(f"  {header}: {response.headers[header]}")
            response.raise_for_status()
        response = await http.post("https://esi.evetech.net/universe/names/", json=[587])
        print(f"{response.status_code} /universe/names/")
        response.raise_for_status()
        for region_id in (10000002, 10000043, 10000032, 10000030, 10000042):
            response = await http.get(
                f"https://esi.evetech.net/markets/{region_id}/orders/",
                params={"type_id": 34, "order_type": "all", "page": 1},
            )
            response.raise_for_status()
            pages = int(response.headers["X-Pages"])
            print(f"{response.status_code} region={region_id} pages={pages}")
            response = await http.get(
                f"https://esi.evetech.net/markets/{region_id}/history/", params={"type_id": 34}
            )
            response.raise_for_status()
            print(f"{response.status_code} history region={region_id} days={len(response.json())}")


if __name__ == "__main__":
    asyncio.run(main())
