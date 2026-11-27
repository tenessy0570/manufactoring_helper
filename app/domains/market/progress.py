from app.core.cache import Cache
from app.domains.market.models import HubId


class MarketSyncProgress:
    def __init__(self, cache: Cache) -> None:
        self._cache = cache

    async def update(self, hub: HubId, completed: int, total: int) -> None:
        await self._cache.set(f"market-sync-progress:{hub}", [completed, total], 300)

    async def get(self, hub: HubId) -> tuple[int, int] | None:
        value = await self._cache.get(f"market-sync-progress:{hub}")
        if isinstance(value, list) and len(value) == 2:
            completed, total = value
            if isinstance(completed, int) and isinstance(total, int) and total > 0:
                return completed, total
        return None

    async def clear(self, hub: HubId) -> None:
        await self._cache.delete(f"market-sync-progress:{hub}")
