import json
from pathlib import Path
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.orm import Base
from app.domains.history.repository import SQLHistoryRepository
from app.domains.invention.calculation import price_plans
from app.domains.invention.models import InventionRequest, InventionSettings
from app.domains.invention.repository import InventionRepository
from app.domains.manufacturing.models import ManufacturingQuery
from app.domains.manufacturing.service import ManufacturingService
from tests.domains.catalog.test_catalog import NOW
from tests.domains.invention.test_invention import get_plan
from tests.domains.manufacturing.test_manufacturing import seed
from tests.domains.market.test_market import price

CASES = json.loads(
    Path("tests/fixtures/manufacturing-before-refactor.json").read_text(encoding="utf-8")
)


async def test_all_opportunity_fields_match_pre_refactor_responses() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as session:
        repository = await seed(session)
        invention = AsyncMock(spec=InventionRepository)
        requests = {}
        for type_id in (10, 20):
            settings = InventionSettings(type_id=type_id)
            result = price_plans(
                [get_plan(seconds_per_attempt="3600", copying_seconds_per_run="1800")],
                {34: price(34, sell_price="3")},
                settings,
            )
            requests[settings.key] = InventionRequest(
                key=settings.key,
                settings=settings,
                result=result,
                status="ready",
                updated_at=NOW,
                expires_at=NOW.replace(year=NOW.year + 1),
            )
        invention.get_requests.return_value = requests
        service = ManufacturingService(
            repository, SQLHistoryRepository(session), lambda: NOW, invention=invention
        )
        cases = CASES
        for case in cases:
            page = await service.get_opportunities(ManufacturingQuery.model_validate(case["query"]))
            for opportunity in page.items:
                if opportunity.meta_group_id == 2:
                    assert opportunity.bpc_manufacturing_runs == 10
                    assert opportunity.bpc_manufacturing_seconds == opportunity.seconds * 10
                else:
                    assert opportunity.bpc_manufacturing_seconds is None
            assert (
                page.model_dump(
                    mode="json",
                    exclude={
                        "items": {
                            "__all__": {
                                "daily_production_units",
                                "daily_volume_share_pct",
                                "bpc_manufacturing_seconds",
                                "bpc_manufacturing_runs",
                                "price_change_pct",
                                "historical_median_price",
                            }
                        }
                    },
                )
                == case["expected"]
            ), case["query"]
    await engine.dispose()
