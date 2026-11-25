import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pydantic import JsonValue

from app.core.cache import CacheService
from app.core.config import DEFAULT_REFRESH, RefreshPolicy
from app.core.repository import UnitOfWork
from app.domains.invention.calculation import price_plans
from app.domains.invention.gateway import InventionGateway
from app.domains.invention.models import (
    InventionRequest,
    InventionSettings,
    InventionView,
    PlanState,
)
from app.domains.invention.queue import InventionQueue
from app.domains.invention.repository import InventionRepository
from app.domains.manufacturing.repository import ManufacturingRepository


class InventionService:
    def __init__(
        self,
        repository: InventionRepository,
        queue: InventionQueue,
        unit_of_work: UnitOfWork,
        cache: CacheService,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository, self._queue, self._unit_of_work = repository, queue, unit_of_work
        self._cache, self._clock = cache, clock

    async def get_invention_view(self, settings: InventionSettings) -> InventionView:
        request = (await self._repository.get_requests([settings.key])).get(settings.key)
        if request is None:
            return InventionView(request=None, stale=True)
        payload = request.model_dump(mode="json")
        revision = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

        async def load() -> JsonValue:
            return payload

        cached = await self._cache.get_or_load(
            f"invention:{request.key}:{revision}",
            load,
            ttl_seconds=60,
        )
        request = InventionRequest.model_validate(cached)
        return InventionView(
            request=request,
            stale=request.status not in ("ready", "unsupported")
            or request.expires_at <= self._clock(),
        )

    async def prepare(self, settings: InventionSettings) -> InventionView:
        view = await self.get_invention_view(settings)
        if (
            view.request is not None
            and not view.stale
            and view.request.status in ("ready", "unsupported")
        ):
            return view
        now = self._clock()
        await self._repository.ensure_request(
            InventionRequest(key=settings.key, settings=settings, updated_at=now, expires_at=now)
        )
        await self._unit_of_work.commit()
        queued = await self._queue.enqueue(settings)
        view = await self.get_invention_view(settings)
        view.queued = queued
        return view


class InventionSyncService:
    def __init__(
        self,
        repository: InventionRepository,
        gateway: InventionGateway,
        manufacturing: ManufacturingRepository,
        unit_of_work: UnitOfWork,
        plan_ttl_seconds: int = DEFAULT_REFRESH.invention_plan_seconds,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        refresh_policy: RefreshPolicy = DEFAULT_REFRESH,
    ) -> None:
        self._repository, self._gateway, self._manufacturing = repository, gateway, manufacturing
        self._unit_of_work, self._cache_ttl_seconds, self._clock = (
            unit_of_work,
            plan_ttl_seconds,
            clock,
        )
        self._refresh_policy = refresh_policy

    async def sync(self, settings: InventionSettings) -> InventionRequest:
        now = self._clock()
        existing = (await self._repository.get_requests([settings.key])).get(settings.key)
        if (
            existing is not None
            and existing.expires_at > now
            and existing.status in ("ready", "unsupported")
        ):
            return existing
        plan = await self._repository.get_cached_plan(settings.plan_key)
        if plan is None or plan.expires_at <= now:
            plans = await self._gateway.fetch(settings)
            now = self._clock()
            plan = PlanState(
                key=settings.plan_key,
                plans=plans,
                synced_at=now,
                expires_at=now + timedelta(seconds=self._cache_ttl_seconds),
            )
            try:
                await self._repository.save_plan(plan)
                await self._unit_of_work.commit()
            except BaseException:
                await self._unit_of_work.rollback()
                raise
        material_ids = sorted(
            {material.type_id for option in plan.plans for material in option.materials}
        )
        quotes = await self._manufacturing.get_quotes(settings.hub_id, material_ids)
        result = price_plans(plan.plans, quotes, settings)
        now = self._clock()
        expires_at = now + timedelta(seconds=self._refresh_policy.invention_price_seconds)
        status = (
            "ready"
            if result.best is not None
            else "missing_prices"
            if plan.plans
            else "unsupported"
        )
        if status == "missing_prices":
            expires_at = now + timedelta(seconds=self._refresh_policy.retry_seconds)
        request = InventionRequest(
            key=settings.key,
            settings=settings,
            result=result,
            status=status,
            updated_at=now,
            expires_at=expires_at,
        )
        try:
            await self._repository.save_request(request)
            await self._unit_of_work.commit()
        except BaseException:
            await self._unit_of_work.rollback()
            raise
        return request

    async def record_error(self, settings: InventionSettings, error_type: str) -> None:
        previous = (await self._repository.get_requests([settings.key])).get(settings.key)
        now = self._clock()
        request = previous or InventionRequest(
            key=settings.key, settings=settings, updated_at=now, expires_at=now
        )
        request.status, request.error_type = "error", error_type
        request.expires_at = now + timedelta(seconds=self._refresh_policy.retry_seconds)
        await self._repository.save_request(request)
        await self._unit_of_work.commit()
