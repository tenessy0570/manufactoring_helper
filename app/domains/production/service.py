from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid4

from app.core.application_errors import ErrorKind
from app.core.config import DEFAULT_REFRESH, RefreshPolicy
from app.core.freshness import refresh_deadline
from app.core.repository import UnitOfWork
from app.domains.catalog.models import ItemTypeClause
from app.domains.catalog.repository import ItemTypeRepository
from app.domains.invention.models import ShoppingOption, ShoppingPlan
from app.domains.invention.shopping import ShoppingService, ceiling
from app.domains.manufacturing.repository import ManufacturingRepository
from app.domains.production.errors import ProductionError
from app.domains.production.models import (
    BatchInput,
    DecryptorEstimate,
    Entry,
    EntryInput,
    Estimate,
    EstimateInput,
    Production,
    ProductionCreate,
    ProductionDetails,
    ProductionPurchaseList,
    PurchaseListInput,
    PurchaseMaterial,
)
from app.domains.production.repository import ProductionRepository


class ProductionService:
    def __init__(
        self,
        repository: ProductionRepository,
        catalog: ItemTypeRepository,
        unit_of_work: UnitOfWork,
    ) -> None:
        self.repository, self.catalog, self.uow = repository, catalog, unit_of_work

    async def find(self, user_id: UUID, offset: int = 0, limit: int = 50) -> list[Production]:
        return await self.repository.find(user_id, offset, limit)

    async def get(self, user_id: UUID, production_id: UUID, lock: bool = False) -> Production:
        production = await self.repository.get(user_id, production_id, lock)
        if production is None:
            raise ProductionError(ErrorKind.NOT_FOUND, "Production not found")
        return production

    async def persist(self, production: Production) -> Production:
        production.updated_at = datetime.now(UTC)
        try:
            await self.repository.save(production)
            await self.uow.commit()
        except BaseException:
            await self.uow.rollback()
            raise
        return production

    async def create(self, user_id: UUID, data: ProductionCreate) -> Production:
        items = await self.catalog.find(ItemTypeClause(type_ids=[data.type_id], is_active=None))
        if not items:
            raise ProductionError(ErrorKind.INVALID_INPUT, "Select a product from the catalog")
        now = datetime.now(UTC)
        return await self.persist(
            Production(
                **data.model_dump(),
                id=uuid4(),
                user_id=user_id,
                name=items[0].name,
                created_at=now,
                updated_at=now,
            )
        )

    async def update(
        self, user_id: UUID, production_id: UUID, data: ProductionDetails
    ) -> Production:
        production = await self.get(user_id, production_id, lock=True)
        production.units, production.comment, production.status = (
            data.units,
            data.comment,
            data.status,
        )
        production.actual_units = data.actual_units
        production.actual_runs = data.actual_runs
        return await self.persist(production)

    async def entry(
        self, user_id: UUID, production_id: UUID, data: EntryInput, entry_id: UUID | None = None
    ) -> Production:
        production = await self.get(user_id, production_id, lock=True)
        if entry_id is None:
            production.entries.append(
                Entry(**data.model_dump(), id=uuid4(), created_at=datetime.now(UTC))
            )
        else:
            existing = next((entry for entry in production.entries if entry.id == entry_id), None)
            if existing is None:
                raise ProductionError(ErrorKind.NOT_FOUND, "Entry not found")
            existing.kind, existing.amount, existing.comment = data.kind, data.amount, data.comment
        return await self.persist(production)

    async def delete_entry(self, user_id: UUID, production_id: UUID, entry_id: UUID) -> Production:
        production = await self.get(user_id, production_id, lock=True)
        remaining = [entry for entry in production.entries if entry.id != entry_id]
        if len(remaining) == len(production.entries):
            raise ProductionError(ErrorKind.NOT_FOUND, "Entry not found")
        production.entries = remaining
        return await self.persist(production)

    async def delete(self, user_id: UUID, production_id: UUID) -> None:
        await self.get(user_id, production_id, lock=True)
        try:
            await self.repository.delete(user_id, production_id)
            await self.uow.commit()
        except BaseException:
            await self.uow.rollback()
            raise


class ProductionEstimateService:
    def __init__(
        self,
        productions: ProductionService,
        market: ManufacturingRepository,
        shopping: ShoppingService,
        refresh_policy: RefreshPolicy = DEFAULT_REFRESH,
    ) -> None:
        self.productions, self.market, self.shopping = productions, market, shopping
        self._refresh = refresh_policy

    async def estimate(self, user_id: UUID, production_id: UUID, data: EstimateInput) -> Estimate:
        production = await self.productions.get(user_id, production_id)
        if data.kind == "invention":
            assert data.units is not None
            plan, selected = await self.invention_option(production.type_id, data)
            if selected.estimated_cost is None:
                raise ProductionError(
                    ErrorKind.CONFLICT,
                    "Prices for this decryptor option are missing. Try another option.",
                )
            amount = selected.estimated_cost
            description = (
                f"{data.units:,} units; {selected.decryptor_name or 'No decryptor'}; "
                f"{selected.attempts} expected attempts; "
                f"{selected.probability * 100:.1f}% chance; "
                f"{selected.runs_per_copy} runs / T2 BPC. "
                "Skills II/II/II; excludes T1 BPC costs."
            )
            return Estimate(
                amount=amount.quantize(Decimal(".01"), rounding=ROUND_HALF_UP),
                description=description,
                stale=plan.stale,
                complete_comparison=plan.complete_pricing,
                selected_decryptor_id=selected.decryptor_id,
                decryptor_options=[
                    DecryptorEstimate(
                        decryptor_id=option.decryptor_id,
                        name=option.decryptor_name
                        if option.decryptor_id is not None
                        else "No decryptor",
                        probability=option.probability,
                        runs_per_copy=option.runs_per_copy,
                        estimated_cost=option.estimated_cost,
                        is_best=plan.best is not None
                        and option.decryptor_id == plan.best.decryptor_id,
                    )
                    for option in plan.options
                ],
            )
        state = (await self.market.recipes([production.type_id])).get(production.type_id)
        if state is None or state.recipe is None:
            raise ProductionError(
                ErrorKind.CONFLICT,
                "No saved manufacturing recipe. Wait for the background recipe sync.",
            )
        recipe = state.recipe
        runs = batch_runs(data, recipe.units)
        stale = state.expires_at <= datetime.now(UTC)
        if data.kind == "manufacturing":
            if recipe.estimated_item_value is None and (
                data.facility_tax or data.system_cost_index
            ):
                raise ProductionError(
                    ErrorKind.CONFLICT,
                    "Recipe needs an estimated item value. Wait for its refresh.",
                )
            amount = runs * (
                recipe.job_cost
                + (recipe.estimated_item_value or Decimal(0))
                * (data.facility_tax + data.system_cost_index)
                / 100
            )
            description = f"{runs:,} runs; base/SCC charge plus facility tax and system cost index."
        else:
            quotes = await self.market.quotes(
                data.hub_id, [material.type_id for material in recipe.materials]
            )
            amount = Decimal(0)
            for material in recipe.materials:
                quote = quotes.get(material.type_id)
                price = (
                    None
                    if quote is None
                    else quote.buy_price
                    if data.material_order_type == "buy"
                    else quote.sell_price
                )
                if price is None or price <= 0:
                    raise ProductionError(
                        ErrorKind.CONFLICT,
                        "Material prices are missing. Try another hub or wait for the market sync.",
                    )
                amount += runs * material.quantity * price
                assert quote is not None
                stale = stale or refresh_deadline(
                    quote.synced_at, self._refresh.market
                ) <= datetime.now(UTC)
            if data.material_order_type == "buy":
                amount *= 1 + data.buy_broker_fee / 100
            description = (
                f"{runs:,} runs / {runs * recipe.units:,} units; "
                f"{data.hub_id.title()} {data.material_order_type} prices; ME 0."
            )
        return Estimate(
            amount=amount.quantize(Decimal(".01"), rounding=ROUND_HALF_UP),
            description=description,
            stale=stale,
        )

    async def invention_option(
        self, type_id: int, data: EstimateInput | PurchaseListInput
    ) -> tuple[ShoppingPlan, ShoppingOption]:
        assert data.units is not None
        plan = await self.shopping.plan(type_id, data.units, data.hub_id)
        selected = (
            plan.best
            if data.decryptor_id == "best"
            else next(
                (option for option in plan.options if option.decryptor_id == data.decryptor_id),
                None,
            )
        )
        if selected is None:
            raise ProductionError(
                ErrorKind.CONFLICT if data.decryptor_id == "best" else ErrorKind.INVALID_INPUT,
                "No priced invention plan. Prepare it in Invention shopping, then retry."
                if data.decryptor_id == "best"
                else "This decryptor is not available for this blueprint.",
            )
        return plan, selected

    async def purchase_list(
        self, user_id: UUID, production_id: UUID, data: PurchaseListInput
    ) -> ProductionPurchaseList:
        production = await self.productions.get(user_id, production_id)
        if data.kind == "invention":
            assert data.units is not None
            plan, selected = await self.invention_option(production.type_id, data)
            return ProductionPurchaseList(
                materials=[
                    PurchaseMaterial(type_id=m.type_id, quantity=m.quantity)
                    for m in selected.materials
                ],
                description=(
                    f"{selected.attempts:,} expected attempts; "
                    f"{selected.decryptor_name or 'No decryptor'}. "
                    "Skills II/II/II. T1 BPCs excluded; success is not guaranteed."
                ),
                stale=plan.stale,
            )
        state = (await self.market.recipes([production.type_id])).get(production.type_id)
        if state is None or state.recipe is None:
            raise ProductionError(
                ErrorKind.CONFLICT,
                "No saved manufacturing recipe. Wait for the background recipe sync.",
            )
        runs = batch_runs(data, state.recipe.units)
        return ProductionPurchaseList(
            materials=[
                PurchaseMaterial(type_id=m.type_id, quantity=m.quantity * runs)
                for m in state.recipe.materials
            ],
            description=f"{runs:,} runs / {runs * state.recipe.units:,} units; ME 0.",
            stale=state.expires_at <= datetime.now(UTC),
        )


def batch_runs(data: BatchInput, units_per_run: int) -> int:
    if data.manufacturing_runs is not None:
        return data.manufacturing_runs
    assert data.units is not None
    return ceiling(Decimal(data.units) / units_per_run)
