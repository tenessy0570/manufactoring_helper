from unittest.mock import AsyncMock

import pytest
from dishka import Provider, Scope, make_async_container
from httpx import ASGITransport, AsyncClient

from app.core.cache import CacheService, MemoryCache
from app.domains.catalog.gateway import CatalogGateway
from app.domains.catalog.names import ItemNameService, ItemNamesUnavailableError
from app.main import create_app
from tests.helpers import make_settings


async def test_names_are_batched_deduplicated_and_cached() -> None:
    gateway = AsyncMock(spec=CatalogGateway)
    gateway.resolve_names.return_value = {34: "Tritanium", 35: "Pyerite"}
    service = ItemNameService(gateway, CacheService(MemoryCache(max_items=100)))
    first = await service.resolve([35, 34, 34])
    assert first.names == {34: "Tritanium", 35: "Pyerite"}
    assert first.missing_type_ids == []
    assert await service.resolve([34, 35]) == first
    gateway.resolve_names.assert_awaited_once_with([34, 35])


async def test_partial_lookup_does_not_cache_missing_names() -> None:
    gateway = AsyncMock(spec=CatalogGateway)
    gateway.resolve_names.side_effect = [{34: "Tritanium"}, {34: "Tritanium", 35: "Pyerite"}]
    service = ItemNameService(gateway, CacheService(MemoryCache(max_items=100)))
    first = await service.resolve([34, 35])
    assert first.names == {34: "Tritanium"}
    assert first.missing_type_ids == [35]
    second = await service.resolve([34, 35])
    assert second.names[35] == "Pyerite"
    assert await service.resolve([35, 34]) == second
    assert gateway.resolve_names.await_count == 2


async def test_failed_name_source_can_be_retried() -> None:
    gateway = AsyncMock(spec=CatalogGateway)
    gateway.resolve_names.side_effect = [ConnectionError("offline"), {34: "Tritanium"}]
    service = ItemNameService(gateway, CacheService(MemoryCache(max_items=100)))
    with pytest.raises(ItemNamesUnavailableError):
        await service.resolve([34])
    assert (await service.resolve([34])).names == {34: "Tritanium"}


async def test_names_api_validates_ids_and_does_not_expose_source_errors() -> None:
    gateway = AsyncMock(spec=CatalogGateway)
    gateway.resolve_names.return_value = {34: "Tritanium"}
    service = ItemNameService(gateway, CacheService(MemoryCache(max_items=100)))
    provider = Provider(scope=Scope.APP)
    provider.provide(lambda: service, provides=ItemNameService)
    container = make_async_container(provider)
    app = create_app(container=container, settings=make_settings())
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/catalog/names?type_ids=34")
            assert response.status_code == 200
            assert response.json() == {"names": {"34": "Tritanium"}, "missing_type_ids": []}
            assert (await client.get("/api/v1/catalog/names")).status_code == 422
            assert (await client.get("/api/v1/catalog/names?type_ids=-1")).status_code == 422
            too_many = "&".join(["type_ids=34"] * 1001)
            assert (await client.get("/api/v1/catalog/names?" + too_many)).status_code == 422
            gateway.resolve_names.side_effect = ConnectionError("internal connection details")
            failed = await client.get("/api/v1/catalog/names?type_ids=35")
            assert failed.status_code == 503
            assert "internal connection details" not in failed.text
    finally:
        await container.close()
