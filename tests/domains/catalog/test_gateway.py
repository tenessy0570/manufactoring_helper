import json

import httpx
import pytest
import respx

from app.domains.catalog.gateway import EsiEverefCatalogGateway
from app.infrastructure.esi import EsiClient
from app.infrastructure.everef import EverefClient
from app.infrastructure.http import HttpStatusError


async def test_gateway_public_endpoints_and_name_batching() -> None:
    async with httpx.AsyncClient(base_url="https://test") as http:
        gateway = EsiEverefCatalogGateway(
            EsiClient(http, 2, 0, lambda: "2026-11-16"), EverefClient(http, 2, 0)
        )
        with respx.mock:
            respx.get("https://test/markets/groups/").respond(200, json=[1])
            respx.get("https://test/markets/groups/1/").respond(
                200,
                json={
                    "market_group_id": 1,
                    "name": "Drones",
                    "types": [10],
                },
            )
            respx.get("https://test/types/10").respond(200, json={"meta_group_id": 2})

            def names(request: httpx.Request) -> httpx.Response:
                ids = json.loads(request.content)
                assert len(ids) <= 1000
                assert "Authorization" not in request.headers
                return httpx.Response(
                    200, json=[{"id": number, "name": str(number)} for number in ids]
                )

            route = respx.post("https://test/universe/names/").mock(side_effect=names)
            assert await gateway.list_market_group_ids() == [1]
            group = await gateway.get_market_group(1)
            assert group is not None
            assert group.types == [10]
            assert await gateway.get_meta_group_id(10) == 2
            assert len(await gateway.resolve_names([*range(1001), 0])) == 1001
            assert route.call_count == 2
            assert await gateway.resolve_names([]) == {}


@pytest.mark.parametrize("status", [404, 503])
async def test_gateway_missing_data_and_failures(status: int) -> None:
    async with httpx.AsyncClient(base_url="https://test") as http:
        gateway = EsiEverefCatalogGateway(
            EsiClient(http, 1, 0, lambda: "2026-11-16"), EverefClient(http, 1, 0)
        )
        with respx.mock:
            respx.get("https://test/markets/groups/1/").respond(status)
            respx.get("https://test/types/1").respond(status)
            for call in (gateway.get_market_group, gateway.get_meta_group_id):
                if status == 404:
                    assert await call(1) is None
                else:
                    with pytest.raises(HttpStatusError):
                        await call(1)
