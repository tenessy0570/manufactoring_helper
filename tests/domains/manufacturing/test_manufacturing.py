import asyncio
import json
import runpy
from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from dishka import Provider, Scope, make_async_container
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.orm import Base
from app.core.repository import SQLAlchemyUnitOfWork, UnitOfWork
from app.domains.catalog.repository import SQLItemTypeRepository
from app.domains.history.repository import SQLHistoryRepository
from app.domains.manufacturing.calculation import calculate
from app.domains.manufacturing.gateway import (
    AmbiguousRecipeError,
    EverefIndustryGateway,
    IndustryClient,
    IndustryGateway,
    parse_duration_seconds,
)
from app.domains.manufacturing.models import (
    CalculationInput,
    CalculatorQuery,
    ManufacturingQuery,
    Material,
    Recipe,
    RecipeState,
)
from app.domains.manufacturing.repository import ManufacturingRepository, SQLManufacturingRepository
from app.domains.manufacturing.service import ManufacturingService, ManufacturingSyncService
from app.domains.market.quotes import SQLMarketQuoteReader
from app.domains.market.repository import SQLMarketRepository
from app.infrastructure.http import HttpStatusError
from app.main import create_app
from tests.domains.catalog.test_catalog import NOW, item
from tests.domains.history.test_history import day
from tests.domains.history.test_history import get_state as history_state
from tests.domains.market.test_market import get_state as market_state
from tests.domains.market.test_market import price
from tests.helpers import make_settings

EXPIRES = NOW + timedelta(days=1)


def recipe(**kwargs: Any) -> Recipe:
    return Recipe.model_validate(
        {
            "type_id": 10,
            "blueprint_id": 11,
            "units": 2,
            "seconds": "3600",
            "job_cost": "4",
            "estimated_item_value": "100",
            "materials": [{"type_id": 34, "quantity": 10}],
            **kwargs,
        }
    )


def recipe_state(type_id: int = 10, **kwargs: Any) -> RecipeState:
    return RecipeState.model_validate(
        {
            "type_id": type_id,
            "recipe": recipe(type_id=type_id),
            "synced_at": NOW,
            "expires_at": EXPIRES,
            **kwargs,
        }
    )


def calculation_input() -> CalculationInput:
    return CalculationInput(
        recipe=recipe(),
        quotes={34: price(34, buy_price="2", sell_price="3")},
        product_quote=price(10, buy_price="25", sell_price="30"),
    )


@pytest.mark.parametrize(
    ("material_mode", "product_mode", "expected"),
    [
        ("sell", "sell", "13"),
        ("sell", "buy", "8"),
        ("buy", "sell", "18"),
        ("buy", "buy", "13"),
    ],
)
def test_independent_pricing_modes_and_multi_unit_output(
    material_mode: str, product_mode: str, expected: str
) -> None:
    query = ManufacturingQuery.model_validate(
        {"material_order_type": material_mode, "product_order_type": product_mode}
    )
    result = calculate(calculation_input(), query)
    assert result is not None
    assert result.profit_per_unit == Decimal(expected)
    assert result.profit_per_day == Decimal(expected) * 48
    assert result.job_cost_per_unit == 2


def test_defaults_taxes_broker_sides_efficiency_and_override() -> None:
    query = ManufacturingQuery()
    assert query.material_order_type == query.product_order_type == "sell"
    assert query.sales_tax == query.broker_fee == 0
    result = calculate(
        calculation_input(), ManufacturingQuery(sales_tax=Decimal(10), broker_fee=Decimal(2))
    )
    assert result is not None
    assert result.sales_tax_per_unit == 3
    assert result.sales_broker_fee_per_unit == Decimal("0.6")
    assert result.procurement_broker_fee_per_unit == 0
    assert result.profit_per_unit == Decimal("9.4")
    result = calculate(
        calculation_input(),
        ManufacturingQuery(
            material_order_type="buy", product_order_type="buy", broker_fee=Decimal(2)
        ),
    )
    assert result is not None
    assert result.procurement_broker_fee_per_unit == Decimal("0.2")
    assert result.sales_broker_fee_per_unit == 0
    result = calculate(calculation_input(), ManufacturingQuery(job_cost_per_run=Decimal(0)))
    assert result is not None
    assert result.materials[0].quantity == 10
    assert result.seconds == 3600
    assert result.job_cost_per_unit == 0


def test_missing_prices_are_not_treated_as_zero() -> None:
    data = calculation_input()
    data.quotes = {}
    assert calculate(data, ManufacturingQuery()) is None
    data = calculation_input()
    data.quotes[34].sell_price = None
    assert calculate(data, ManufacturingQuery()) is None
    data = calculation_input()
    data.product_quote.sell_price = None
    assert calculate(data, ManufacturingQuery()) is None
    data = calculation_input()
    data.quotes[34].sell_price = Decimal(0)
    assert calculate(data, ManufacturingQuery()) is None


@pytest.mark.parametrize("value", ["", "bad", "P", "PT0S", "P1M"])
def test_invalid_duration(value: str) -> None:
    with pytest.raises(ValueError, match=r"duration|Duration"):
        parse_duration_seconds(value)


def test_duration_and_legacy_profit_parity() -> None:
    assert parse_duration_seconds("P1DT2H3M4.5S") == Decimal("93784.5")
    legacy = runpy.run_path("reference/eve_manufacturing_scan.py")
    old = legacy["Opportunity"](
        type_id=10,
        name="test",
        cost=15.0,
        job_cost=2.0,
        revenue=30.0,
        sales_tax=10.0,
        units_per_day=48.0,
    )
    result = calculate(calculation_input(), ManufacturingQuery(sales_tax=Decimal(10)))
    assert result is not None
    assert float(result.profit_per_unit) == old.profit()
    assert float(result.profit_per_day) == old.profit_per_day(old.profit())
    assert float(result.margin_pct) == pytest.approx(old.profit() / old.cost * 100)


def test_saved_snapshot_material_totals_match_original_script() -> None:
    payload = json.loads(
        Path("tests/fixtures/manufacturing.json").read_text(encoding="utf-8"), parse_float=Decimal
    )
    production = payload["manufacturing"]["2454"]
    baseline = Recipe(
        type_id=2454,
        blueprint_id=production["blueprint_id"],
        units=production["units"],
        seconds=parse_duration_seconds(production["time"]),
        job_cost=production["total_job_cost"],
        materials=[Material.model_validate(value) for value in production["materials"].values()],
    )
    quotes = {
        value["type_id"]: price(value["type_id"], sell_price=value["cost_per_unit"])
        for value in production["materials"].values()
    }
    result = calculate(
        CalculationInput(
            recipe=baseline, quotes=quotes, product_quote=price(2454, sell_price="10000")
        ),
        ManufacturingQuery(),
    )
    assert result is not None
    assert result.material_cost_per_unit == production["total_material_cost"] / production["units"]
    assert result.profit_per_unit == Decimal("10000") - production["total_cost_per_unit"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_profit": 10, "max_profit": 1},
        {"min_margin": 10, "max_margin": 1},
        {"sales_tax": 90, "broker_fee": 20},
    ],
)
def test_invalid_settings(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"Minimum|Combined|less than"):
        ManufacturingQuery.model_validate(kwargs)


async def test_gateway_saved_public_fixture_and_errors() -> None:
    payload = json.loads(
        await asyncio.to_thread(
            Path("tests/fixtures/manufacturing.json").read_text, encoding="utf-8"
        )
    )
    async with httpx.AsyncClient(base_url="https://test") as http:
        gateway = EverefIndustryGateway(IndustryClient(http, 1, 0))
        with respx.mock:
            route = respx.get("https://test/v1/industry/cost").respond(200, json=payload)
            result = await gateway.fetch(2454)
            assert result is not None
            assert result.estimated_item_value == Decimal(3668)
            assert result.units == 1
            assert result.seconds == 204
            assert result.materials[0] == Material(type_id=34, quantity=509)
            assert route.calls[0].request.url.params["me"] == "0"
            route.respond(200, json={"manufacturing": {}})
            assert await gateway.fetch(2454) is None
            route.respond(404)
            assert await gateway.fetch(2454) is None
            route.respond(
                400,
                json={
                    "message": (
                        "ClientException: Product type ID 2454 is not produced from a blueprint"
                    )
                },
            )
            assert await gateway.fetch(2454) is None
            route.respond(400, text="invalid response")
            with pytest.raises(Exception, match="400"):
                await gateway.fetch(2454)
            route.respond(400, json={"message": "invalid parameters"})
            with pytest.raises(Exception, match="400"):
                await gateway.fetch(2454)
            route.respond(503)
            with pytest.raises(Exception, match="503"):
                await gateway.fetch(2454)
            payload["manufacturing"]["2454"]["me"] = 10
            route.respond(200, json=payload)
            with pytest.raises(ValueError, match="baseline"):
                await gateway.fetch(2454)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


async def seed(session: AsyncSession) -> SQLManufacturingRepository:
    await SQLItemTypeRepository(session).upsert_many(
        [item(10), item(20), item(30), item(40), item(50)]
    )
    market = SQLMarketRepository(session)
    await market.replace(
        market_state(),
        [
            price(10, sell_price="30"),
            price(20, sell_price="40"),
            price(34, sell_price="3", buy_price="2"),
        ],
    )
    await market.replace(market_state("amarr"), [price(34, hub_id="amarr", sell_price="1")])
    await SQLHistoryRepository(session).replace(history_state(), [day()])
    repository = SQLManufacturingRepository(session, SQLMarketQuoteReader(session))
    for entry in (
        recipe_state(),
        recipe_state(20),
        recipe_state(40, recipe=None),
        recipe_state(50),
    ):
        await repository.save(entry)
    return repository


async def test_repository_batches_json_roundtrip_and_rollback(session: AsyncSession) -> None:
    repository = SQLManufacturingRepository(session, SQLMarketQuoteReader(session))
    assert await repository.get_recipes([10]) == {}
    await repository.save(recipe_state())
    await session.commit()
    assert (await repository.get_recipes(list(range(601))))[10] == recipe_state()
    await repository.save(recipe_state(recipe=None))
    assert (await repository.get_recipes([10]))[10].recipe is None
    await session.rollback()
    assert (await repository.get_recipes([10]))[10].recipe == recipe()
    assert await repository.get_quotes("jita", list(range(601))) == {}


async def test_opportunities_sort_filter_hub_selection_and_missing_counters(
    session: AsyncSession,
) -> None:
    repository = await seed(session)
    service = ManufacturingService(repository, SQLHistoryRepository(session), lambda: NOW)
    page = await service.get_opportunities(ManufacturingQuery())
    assert [entry.type_id for entry in page.items] == [20, 10]
    assert page.items[1].profit_per_unit == 13
    assert page.missing_recipes == page.non_manufacturable == page.missing_prices == 1
    assert page.items[0].invention_required
    assert not page.items[0].invention_included
    for rank in ("margin", "profit"):
        page = await service.get_opportunities(
            ManufacturingQuery.model_validate({"rank_by": rank, "limit": 1, "offset": 1})
        )
        assert page.total == 2
        assert page.items[0].type_id == 10
    page = await service.get_opportunities(ManufacturingQuery(min_profit=Decimal(20)))
    assert [entry.type_id for entry in page.items] == [20]
    page = await service.get_opportunities(
        ManufacturingQuery(material_hub_id="amarr", type_ids=[10])
    )
    assert page.items[0].profit_per_unit == 23
    page = await service.get_opportunities(ManufacturingQuery(min_daily_isk_volume=Decimal(1)))
    assert page.total == 1
    page = await service.get_opportunities(ManufacturingQuery(fresh_only=True))
    assert page.total == 1
    service = ManufacturingService(repository, SQLHistoryRepository(session), lambda: EXPIRES)
    page = await service.get_opportunities(ManufacturingQuery(fresh_only=True))
    assert page.total == 0


async def test_api_defaults_and_validation(session: AsyncSession) -> None:
    repository = await seed(session)
    service = ManufacturingService(repository, SQLHistoryRepository(session), lambda: NOW)
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: service, provides=ManufacturingService)
    container = make_async_container(provider)
    app = create_app(container=container, settings=make_settings(), require_login=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/manufacturing/opportunities")
        assert response.status_code == 200, response.text
        assert response.json()["material_order_type"] == "sell"
        assert response.json()["product_order_type"] == "sell"
        assert response.json()["sales_tax"] == "0"
        legacy = await client.get("/api/v1/manufacturing/opportunities?broker_fee=2")
        assert legacy.status_code == 200
        assert legacy.json()["sell_broker_fee"] == "2"

        taxed = await client.get(
            "/api/v1/manufacturing/opportunities",
            params={
                "type_ids": 10,
                "buy_broker_fee": "2",
                "sell_broker_fee": "3",
                "sales_tax": "10",
                "facility_tax": "1",
                "system_cost_index": "2",
            },
        )
        assert taxed.status_code == 200, taxed.text
        assert taxed.json()["items"][0]["profit_per_unit"] == "7.60"
        for settings in [
            {},
            {"sales_tax": "10", "sell_broker_fee": "3", "facility_tax": "1"},
            {"product_order_type": "buy", "buy_demand_tolerance_pct": "5", "production_lines": "3"},
            {"material_hub_id": "amarr", "material_order_type": "buy"},
            {"include_invention_cost": "true"},
        ]:
            reference = await client.get(
                "/api/v1/manufacturing/opportunities",
                params={
                    **settings,
                    "type_ids": 10,
                    "limit": 1,
                },
            )
            single = await client.get("/api/v1/manufacturing/calculator/10", params=settings)
            assert single.status_code == 200
            assert {
                key: value for key, value in single.json().items() if key != "batch"
            } == reference.json()
        scoped = await client.get(
            "/api/v1/manufacturing/calculator/10",
            params={
                "type_ids": 20,
                "exclude_type_ids": 10,
                "search": "other",
                "offset": 100,
            },
        )
        assert [row["type_id"] for row in scoped.json()["items"]] == [10]
        batch_response = await client.get(
            "/api/v1/manufacturing/calculator/10",
            params={
                "manufacturing_runs": 3,
                "min_profit": 999999,
                "min_margin": 999999,
                "fresh_only": "true",
                "sales_tax": 10,
            },
        )
        batch = batch_response.json()["batch"]
        assert batch["runs"] == 3
        assert batch["units"] == 6
        assert batch["materials"][0]["quantity"] == 30
        assert Decimal(batch["material_cost"]) == 90
        assert Decimal(batch["total_cost"]) == 102
        assert Decimal(batch["gross_revenue"]) == 180
        assert Decimal(batch["net_revenue"]) == 162
        assert Decimal(batch["profit"]) == 60
        assert Decimal(batch["margin_pct"]) == Decimal(60) / 90 * 100
        negative = await client.get(
            "/api/v1/manufacturing/calculator/10",
            params={"manufacturing_runs": 2, "sales_tax": 100, "min_profit": 0},
        )
        assert Decimal(negative.json()["batch"]["profit"]) == -68
        for runs, tax in ((1, 10), (1000000, 0), (1, 100)):
            buy = await client.get(
                "/api/v1/manufacturing/calculator/10",
                params={"manufacturing_runs": runs, "product_order_type": "buy", "sales_tax": tax},
            )
            bought = buy.json()["batch"]
            if bought["covered_units"] < bought["units"]:
                assert bought["profit"] is None
                assert bought["net_revenue"] is None
            else:
                assert Decimal(bought["gross_revenue"]) > 0
                assert Decimal(bought["net_revenue"]) == Decimal(bought["gross_revenue"]) * (
                    1 - Decimal(tax) / 100
                )
        for runs in (0, -1, 1000000001):
            assert (
                await client.get(
                    "/api/v1/manufacturing/calculator/10", params={"manufacturing_runs": runs}
                )
            ).status_code == 422
        assert (await client.get("/api/v1/manufacturing/calculator/0")).status_code == 422
        for field in ("buy_broker_fee", "sell_broker_fee", "facility_tax", "system_cost_index"):
            assert (
                await client.get("/api/v1/manufacturing/opportunities", params={field: "101"})
            ).status_code == 422
            blank = await client.get("/api/v1/manufacturing/opportunities", params={field: ""})
            assert blank.status_code == 200
            assert blank.json()[field] == "0"

        assert (
            await client.get("/api/v1/manufacturing/opportunities?buy_demand_tolerance_pct=")
        ).status_code == 200
        assert (
            await client.get("/api/v1/manufacturing/opportunities?buy_demand_tolerance_pct=101")
        ).status_code == 422
        assert (
            await client.get("/api/v1/manufacturing/opportunities?sales_tax=101")
        ).status_code == 422
    await container.close()


async def test_candidates_past_first_batch_are_ranked_before_pagination(
    session: AsyncSession,
) -> None:
    await SQLItemTypeRepository(session).upsert_many([item(number) for number in range(1, 502)])
    repository = SQLManufacturingRepository(session, SQLMarketQuoteReader(session))
    await repository.save(recipe_state(501))
    await SQLMarketRepository(session).replace(
        market_state(), [price(501, sell_price="30"), price(34, sell_price="3")]
    )
    page = await ManufacturingService(
        repository, SQLHistoryRepository(session), lambda: NOW
    ).get_opportunities(ManufacturingQuery(limit=1))
    assert page.total == 1
    assert page.items[0].type_id == 501
    assert page.missing_recipes == 500


async def test_unavailable_material_and_expired_recipe_are_excluded(session: AsyncSession) -> None:
    repository = await seed(session)
    service = ManufacturingService(repository, SQLHistoryRepository(session), lambda: NOW)
    await repository.save(recipe_state(expires_at=NOW - timedelta(seconds=1)))
    assert (await service.get_opportunities(ManufacturingQuery(fresh_only=True))).total == 0
    await SQLMarketRepository(session).replace(
        market_state(),
        [price(10, sell_price="30"), price(20, sell_price="40"), price(34, sell_price=None)],
    )
    page = await service.get_opportunities(ManufacturingQuery())
    assert page.total == 0
    assert page.missing_prices == 3


async def test_sync_freshness_unsupported_and_failures() -> None:
    repository = AsyncMock(spec=ManufacturingRepository)
    gateway = AsyncMock(spec=IndustryGateway)
    unit_of_work = AsyncMock(spec=SQLAlchemyUnitOfWork)
    repository.get_recipes.return_value = {}
    gateway.fetch.return_value = recipe()
    service = ManufacturingSyncService(repository, gateway, unit_of_work, clock=lambda: NOW)
    assert await service.sync_if_stale(10)
    repository.save.assert_awaited_once()
    repository.get_recipes.return_value = {10: recipe_state()}
    assert not await service.sync_if_stale(10)
    repository.get_recipes.return_value = {}
    gateway.fetch.side_effect = ConnectionError("offline")
    with pytest.raises(ConnectionError, match="offline"):
        await service.sync_if_stale(10)
    gateway.fetch.side_effect = None
    gateway.fetch.return_value = None
    assert await service.sync_if_stale(10)
    assert repository.save.await_args is not None
    assert repository.save.await_args.args[0].recipe is None
    unit_of_work.commit.side_effect = RuntimeError("failed")
    with pytest.raises(RuntimeError, match="failed"):
        await service.sync_if_stale(10)
    unit_of_work.rollback.assert_awaited_once()


async def test_single_buy_order_and_small_volume_are_flagged(session: AsyncSession) -> None:
    repository = await seed(session)
    await SQLMarketRepository(session).replace(
        market_state(),
        [
            price(10, buy_price="30", buy_volume=1, buy_order_count=1, buy_orders_at_best=1),
            price(34, sell_price="3"),
        ],
    )
    service = ManufacturingService(repository, SQLHistoryRepository(session), lambda: NOW)
    page = await service.get_opportunities(
        ManufacturingQuery(type_ids=[10], product_order_type="buy")
    )
    result = page.items[0]
    assert result.profit_per_unit == 13
    assert result.product_order_count == result.orders_at_price == 1
    assert result.full_runs_at_buy_price == 0
    assert result.production_limit_units == 0
    assert result.profit_at_current_buy_price == 0
    assert result.demand_limited_profit_per_day == 0
    assert result.demand_warnings == [
        "single_buy_order",
        "single_buy_order_at_best",
        "insufficient_buy_volume_for_one_run",
    ]
    for kwargs in (
        {"min_product_orders": 2},
        {"min_orders_at_price": 2},
        {"min_product_volume": 2},
        {"require_full_run_demand": True},
        {"exclude_fragile_buy_demand": True},
    ):
        query = ManufacturingQuery.model_validate(
            {"type_ids": [10], "product_order_type": "buy", **kwargs}
        )
        assert (await service.get_opportunities(query)).total == 0
    page = await service.get_opportunities(
        ManufacturingQuery(type_ids=[10], require_full_run_demand=True)
    )
    assert page.total == 1
    assert page.items[0].demand_warnings == []


async def test_buy_ranking_limits_profit_by_absorbable_output(session: AsyncSession) -> None:
    repository = await seed(session)
    await SQLMarketRepository(session).replace(
        market_state(),
        [
            price(10, buy_price="200", buy_volume=2, buy_order_count=10, buy_orders_at_best=2),
            price(20, buy_price="100", buy_volume=100, buy_order_count=1, buy_orders_at_best=1),
            price(34, sell_price="3"),
        ],
    )
    service = ManufacturingService(repository, SQLHistoryRepository(session), lambda: NOW)
    page = await service.get_opportunities(
        ManufacturingQuery(type_ids=[10, 20], product_order_type="buy")
    )
    assert [entry.type_id for entry in page.items] == [20, 10]
    low_volume = page.items[1]
    assert low_volume.profit_per_day == 8784
    assert low_volume.production_limit_units == 2
    assert low_volume.profit_at_current_buy_price == 366
    assert low_volume.rank_profit_per_day == 366
    high_volume = page.items[0]
    assert high_volume.profit_at_current_buy_price == 8300
    assert high_volume.rank_profit_per_day == 3984
    filtered = await service.get_opportunities(
        ManufacturingQuery(
            type_ids=[10, 20], product_order_type="buy", min_profit_per_day=Decimal(1000)
        )
    )
    assert [entry.type_id for entry in filtered.items] == [20]


async def test_unknown_order_counts_and_healthy_buy_demand(session: AsyncSession) -> None:
    repository = await seed(session)
    service = ManufacturingService(repository, SQLHistoryRepository(session), lambda: NOW)
    page = await service.get_opportunities(
        ManufacturingQuery(type_ids=[10], product_order_type="buy")
    )
    assert "buy_order_count_unknown" in page.items[0].demand_warnings
    assert (
        await service.get_opportunities(
            ManufacturingQuery(type_ids=[10], product_order_type="buy", min_product_orders=1)
        )
    ).total == 0
    await SQLMarketRepository(session).replace(
        market_state(),
        [
            price(10, buy_volume=20, buy_order_count=3, buy_orders_at_best=2),
            price(34, sell_price="3"),
        ],
    )
    page = await service.get_opportunities(
        ManufacturingQuery(
            type_ids=[10],
            product_order_type="buy",
            exclude_fragile_buy_demand=True,
            require_full_run_demand=True,
        )
    )
    assert page.total == 1
    assert page.items[0].full_runs_at_buy_price == 10
    assert page.items[0].demand_warnings == []


async def test_multiple_blueprints_are_not_marked_non_manufacturable() -> None:
    from app.domains.manufacturing.gateway import AmbiguousRecipeError

    async with httpx.AsyncClient(base_url="https://test") as http:
        gateway = EverefIndustryGateway(IndustryClient(http, 1, 0))
        with respx.mock:
            respx.get("https://test/v1/industry/cost").respond(
                400,
                json={
                    "message": (
                        "ClientException: Product type ID 21527 "
                        "can be source from more than one blueprint"
                    )
                },
            )
            with pytest.raises(AmbiguousRecipeError):
                await gateway.fetch(21527)


@pytest.mark.parametrize("meta_group", [1, 2, 3, 4, 5, 6, 14, 15, None])
async def test_mass_production_group_limit_cannot_be_overridden(
    session: AsyncSession, meta_group: int | None
) -> None:
    await SQLItemTypeRepository(session).upsert_many([item(10, meta_group_id=meta_group)])
    repository = SQLManufacturingRepository(session, SQLMarketQuoteReader(session))
    await repository.save(recipe_state())
    await SQLMarketRepository(session).replace(
        market_state(), [price(10, sell_price="30"), price(34, sell_price="3")]
    )
    service = ManufacturingService(repository, SQLHistoryRepository(session), lambda: NOW)
    for selected in (None, [meta_group] if meta_group is not None else [], [1, 2, 3, 4, 5, 6]):
        page = await service.get_opportunities(ManufacturingQuery(meta_group_ids=selected))
        assert [value.type_id for value in page.items] == ([10] if meta_group in (1, 2) else [])
    if meta_group in (1, 2):
        await repository.save(recipe_state(recipe=None))
        page = await service.get_opportunities(ManufacturingQuery())
        assert page.items == []
        assert page.non_manufacturable == 1


async def test_total_demand_profit_sorting_precedes_pagination(session: AsyncSession) -> None:
    repository = await seed(session)
    await repository.save(recipe_state(20, recipe=recipe(type_id=20, seconds="1000000")))
    await SQLMarketRepository(session).replace(
        market_state(),
        [
            price(10, buy_price="200", buy_volume=3),
            price(20, buy_price="100", buy_volume=100),
            price(34, sell_price="3"),
        ],
    )
    service = ManufacturingService(repository, SQLHistoryRepository(session), lambda: NOW)
    daily = await service.get_opportunities(
        ManufacturingQuery(type_ids=[10, 20], product_order_type="buy", rank_by="profit_per_day")
    )
    assert daily.items[0].type_id == 10
    total = await service.get_opportunities(
        ManufacturingQuery(
            type_ids=[10, 20], product_order_type="buy", rank_by="demand_profit", limit=1
        )
    )
    assert total.total == 2
    assert total.items[0].type_id == 20
    assert total.items[0].profit_at_current_buy_price == 8300
    remainder = await service.get_opportunities(
        ManufacturingQuery(type_ids=[10], product_order_type="buy", rank_by="demand_profit")
    )
    assert remainder.items[0].production_limit_units == 2
    assert remainder.items[0].profit_at_current_buy_price == 366
    sells = await service.get_opportunities(
        ManufacturingQuery(type_ids=[10, 20], product_order_type="sell", rank_by="demand_profit")
    )
    assert [item.type_id for item in sells.items] == [10, 20]
    assert all(item.profit_at_current_buy_price is None for item in sells.items)


async def test_demand_band_changes_volume_weighted_profit_and_sort(session: AsyncSession) -> None:
    from app.domains.market.models import BuyPriceLevel

    repository = await seed(session)
    await SQLMarketRepository(session).replace(
        market_state(),
        [
            price(
                10,
                buy_price="200",
                buy_volume=2,
                buy_orders_at_best=1,
                buy_order_count=21,
                buy_levels=[
                    BuyPriceLevel(price=Decimal(200), volume=2, order_count=1),
                    BuyPriceLevel(price=Decimal(190), volume=100, order_count=20),
                ],
            ),
            price(
                20,
                buy_price="250",
                buy_volume=10,
                buy_orders_at_best=2,
                buy_order_count=2,
                buy_levels=[
                    BuyPriceLevel(price=Decimal(250), volume=10, order_count=2),
                ],
            ),
            price(34, sell_price="3"),
        ],
    )
    service = ManufacturingService(repository, SQLHistoryRepository(session), lambda: NOW)
    query = ManufacturingQuery(type_ids=[10, 20], product_order_type="buy", rank_by="demand_profit")
    result = await service.get_opportunities(query)
    assert [i.type_id for i in result.items] == [10, 20]
    first = result.items[0]
    assert first.buy_demand_volume == 102
    assert first.product_volume_at_price == 2
    assert first.profit_at_current_buy_price == 17666
    assert first.rank_profit_per_day == 8324
    assert first.demand_warnings == []
    query.buy_demand_tolerance_pct = Decimal(0)
    exact = await service.get_opportunities(query)
    assert [i.type_id for i in exact.items] == [20, 10]
    assert exact.items[1].profit_at_current_buy_price == 366


async def test_missing_eiv_is_visible_and_backfilled_without_waiting_for_ttl(
    session: AsyncSession,
) -> None:
    repository = await seed(session)
    await repository.save(recipe_state(recipe=recipe(estimated_item_value=None)))
    service = ManufacturingService(repository, SQLHistoryRepository(session), lambda: NOW)
    query = ManufacturingQuery(type_ids=[10], facility_tax=Decimal(1), system_cost_index=Decimal(2))
    missing = await service.get_opportunities(query)
    assert missing.total == 0
    assert missing.missing_job_costs == 1
    assert missing.missing_prices == 0
    gateway = AsyncMock(spec=IndustryGateway)
    gateway.fetch.return_value = recipe()
    sync = ManufacturingSyncService(
        repository, gateway, SQLAlchemyUnitOfWork(session), clock=lambda: NOW
    )
    assert await sync.sync_if_stale(10)
    updated = await service.get_opportunities(query)
    assert updated.missing_job_costs == 0
    assert updated.items[0].job_cost_per_unit == Decimal("3.5")
    assert updated.buy_broker_fee == updated.sell_broker_fee == 0
    assert updated.facility_tax == 1
    assert updated.system_cost_index == 2


@pytest.mark.parametrize(
    "expired_source", ["product", "material", "history", "missing_history", "recipe"]
)
async def test_candidate_badge_and_fresh_filter_share_schedule_rules(
    session: AsyncSession, expired_source: str
) -> None:
    repository = await seed(session)
    market = SQLMarketRepository(session)
    recent = NOW - timedelta(minutes=19)
    await market.replace(
        market_state(),
        [
            price(10, sell_price="30", synced_at=recent, expires_at=NOW - timedelta(minutes=14)),
            price(34, sell_price="3", synced_at=recent, expires_at=NOW - timedelta(minutes=14)),
        ],
    )
    history = SQLHistoryRepository(session)
    await history.replace(
        history_state().model_copy(
            update={"synced_at": NOW - timedelta(hours=23), "expires_at": NOW - timedelta(hours=1)}
        ),
        [],
    )
    service = ManufacturingService(repository, history, lambda: NOW)
    query = ManufacturingQuery(type_ids=[10])
    page = await service.get_opportunities(query)
    assert not page.items[0].stale
    assert page.items[0].fresh_until == NOW + timedelta(minutes=1)
    assert (
        await service.get_opportunities(query.model_copy(update={"fresh_only": True}))
    ).total == 1
    if expired_source in ("product", "material"):
        old = NOW - timedelta(minutes=20)
        await market.replace(
            market_state(),
            [
                price(
                    10, sell_price="30", synced_at=old if expired_source == "product" else recent
                ),
                price(
                    34, sell_price="3", synced_at=old if expired_source == "material" else recent
                ),
            ],
        )
    elif expired_source == "recipe":
        await repository.save(recipe_state(expires_at=NOW))
    else:
        await history.replace(
            history_state().model_copy(update={"synced_at": NOW - timedelta(days=1)}), []
        )
        if expired_source == "missing_history":
            from sqlalchemy import delete

            from app.domains.history.tables import HistoryStateTable

            await session.execute(delete(HistoryStateTable))
    page = await service.get_opportunities(query)
    assert page.items[0].stale
    assert page.items[0].fresh_until == NOW
    assert (
        await service.get_opportunities(query.model_copy(update={"fresh_only": True}))
    ).total == 0


async def test_material_hub_freshness_does_not_use_product_hub_material_prices(
    session: AsyncSession,
) -> None:
    repository = await seed(session)
    await SQLMarketRepository(session).replace(
        market_state("amarr"),
        [
            price(34, hub_id="amarr", synced_at=NOW - timedelta(minutes=20)),
        ],
    )
    service = ManufacturingService(repository, SQLHistoryRepository(session), lambda: NOW)
    assert not (await service.get_opportunities(ManufacturingQuery(type_ids=[10]))).items[0].stale
    assert (
        (
            await service.get_opportunities(
                ManufacturingQuery(type_ids=[10], material_hub_id="amarr")
            )
        )
        .items[0]
        .stale
    )


async def test_manual_calculator_accepts_non_mass_production_blueprint(
    session: AsyncSession,
) -> None:
    await SQLItemTypeRepository(session).upsert_many([item(60, meta_group_id=3)])
    repository = SQLManufacturingRepository(session, SQLMarketQuoteReader(session))
    await repository.save(recipe_state(60))
    await SQLMarketRepository(session).replace(
        market_state(), [price(60, sell_price="30"), price(34, sell_price="3")]
    )
    service = ManufacturingService(repository, SQLHistoryRepository(session), lambda: NOW)
    assert (await service.get_opportunities(ManufacturingQuery(type_ids=[60]))).items == []
    result = await service.get_calculator_page(60, CalculatorQuery(manufacturing_runs=2))
    assert result.items[0].type_id == 60
    assert result.batch is not None
    assert result.batch.units == 4
    assert result.batch.profit == 52


@pytest.mark.parametrize("initial", ["missing", "expired", "legacy"])
async def test_calculator_refreshes_selected_recipe_and_reuses_fresh_cache(
    session: AsyncSession, initial: str
) -> None:
    repository = await seed(session)
    if initial == "missing":
        type_id = 30
    else:
        type_id = 10
        state = recipe_state(
            recipe=recipe(estimated_item_value=None) if initial == "legacy" else recipe(),
            expires_at=NOW - timedelta(seconds=1) if initial == "expired" else EXPIRES,
        )
        await repository.save(state)
    gateway = AsyncMock(spec=IndustryGateway)
    gateway.fetch.return_value = recipe(type_id=type_id)
    sync = ManufacturingSyncService(
        repository, gateway, AsyncMock(spec=UnitOfWork), clock=lambda: NOW
    )
    service = ManufacturingService(
        repository, SQLHistoryRepository(session), lambda: NOW, sync=sync
    )
    query = CalculatorQuery(facility_tax=Decimal(1), system_cost_index=Decimal(2))
    result = await service.get_calculator_page(type_id, query)
    if type_id == 10:
        assert result.batch is not None
        assert result.batch.facility_tax == 1
        assert result.batch.system_cost == 2
    assert (await repository.get_recipes([type_id]))[type_id].recipe == recipe(type_id=type_id)
    await service.get_calculator_page(type_id, query)
    gateway.fetch.assert_awaited_once_with(type_id)


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (AmbiguousRecipeError("ambiguous"), 409),
        (HttpStatusError(503, "https://test"), 503),
        (httpx.ConnectError("offline"), 503),
    ],
)
async def test_calculator_refresh_errors_are_actionable(error: Exception, status: int) -> None:
    service = AsyncMock(spec=ManufacturingService)
    service.get_calculator_page.side_effect = error
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: service, provides=ManufacturingService)
    container = make_async_container(provider)
    app = create_app(container=container, settings=make_settings(), require_login=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/manufacturing/calculator/10")
        assert response.status_code == status
        assert response.json()["detail"]
    await container.close()
