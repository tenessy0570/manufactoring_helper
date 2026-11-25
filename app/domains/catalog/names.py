import hashlib

from pydantic import JsonValue

from app.core.cache import CacheService
from app.domains.catalog.gateway import CatalogGateway
from app.domains.catalog.models import ItemNamesResult


class ItemNamesUnavailableError(Exception):
    pass


class _IncompleteItemNamesError(Exception):
    def __init__(self, names: dict[int, str]) -> None:
        self.names = names


class ItemNameService:
    def __init__(
        self, gateway: CatalogGateway, cache: CacheService, ttl_seconds: int = 604800
    ) -> None:
        self._gateway, self._cache = gateway, cache
        self._cache_ttl_seconds = ttl_seconds

    async def resolve(self, type_ids: list[int]) -> ItemNamesResult:
        ids = sorted(set(type_ids))
        digest = hashlib.sha256(",".join(map(str, ids)).encode()).hexdigest()

        async def load() -> JsonValue:
            try:
                resolved = await self._gateway.resolve_names(ids)
            except Exception as error:
                raise ItemNamesUnavailableError("Item names are temporarily unavailable") from error
            names = {key: name for key, name in resolved.items() if key in ids}
            if any(key not in names for key in ids):
                raise _IncompleteItemNamesError(names)
            return {str(key): name for key, name in names.items()}

        try:
            values = await self._cache.get_or_load(
                f"item-names:v1:{digest}", load, self._cache_ttl_seconds
            )
            names = ItemNamesResult.model_validate({"names": values, "missing_type_ids": []}).names
        except _IncompleteItemNamesError as error:
            names = error.names
        return ItemNamesResult(
            names=names, missing_type_ids=[key for key in ids if key not in names]
        )
