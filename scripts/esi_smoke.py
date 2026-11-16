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


if __name__ == "__main__":
    asyncio.run(main())
