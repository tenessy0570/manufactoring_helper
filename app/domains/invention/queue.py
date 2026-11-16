from abc import ABC, abstractmethod

from arq.connections import ArqRedis

from app.domains.invention.models import QUEUE, InventionQuery, InventionSettings


class InventionQueue(ABC):
    @abstractmethod
    async def enqueue(self, settings: InventionSettings) -> bool: ...

    @abstractmethod
    async def enqueue_catalog(self, query: InventionQuery | None = None) -> bool: ...


class RedisInventionQueue(InventionQueue):
    def __init__(self, redis: ArqRedis) -> None:
        self._redis = redis

    async def enqueue(self, settings: InventionSettings) -> bool:
        job = await self._redis.enqueue_job(
            "sync_invention",
            settings.model_dump(mode="json"),
            _queue_name=QUEUE,
            _job_id=f"invention:{settings.key}",
        )
        return job is not None

    async def enqueue_catalog(self, query: InventionQuery | None = None) -> bool:
        payload = None if query is None else query.model_dump(mode="json")
        import hashlib
        import json

        suffix = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        job = await self._redis.enqueue_job(
            "schedule_inventions", payload, _queue_name=QUEUE, _job_id=f"invention:planner:{suffix}"
        )
        return job is not None
