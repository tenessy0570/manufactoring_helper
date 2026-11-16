from abc import ABC, abstractmethod
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field


class FilterClause(BaseModel):
    """Declarative filter: every field that is not None becomes an equality condition.

    Subclasses with richer conditions (ranges, IN) are handled by the concrete repository.
    """

    model_config = ConfigDict(frozen=True)


class Page(BaseModel):
    model_config = ConfigDict(frozen=True)

    limit: int = Field(default=100, ge=1, le=10_000)
    offset: int = Field(default=0, ge=0)


class Repository[EntityT: BaseModel, ClauseT: FilterClause](ABC):
    """Persistence port. Services depend on this, never on a concrete storage."""

    @abstractmethod
    async def get(self, entity_id: object) -> EntityT | None: ...

    @abstractmethod
    async def find(
        self, clause: ClauseT | None = None, page: Page | None = None
    ) -> list[EntityT]: ...

    @abstractmethod
    async def count(self, clause: ClauseT | None = None) -> int: ...

    @abstractmethod
    async def add(self, entity: EntityT) -> EntityT: ...

    @abstractmethod
    async def add_many(self, entities: Sequence[EntityT]) -> None: ...

    @abstractmethod
    async def delete(self, entity_id: object) -> bool: ...
