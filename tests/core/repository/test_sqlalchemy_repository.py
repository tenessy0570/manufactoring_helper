from app.core.repository import Page
from tests.core.repository.conftest import Item, ItemClause, ItemRepository


async def seed(repository: ItemRepository) -> None:
    await repository.add_many(
        [
            Item(id=1, name="rig", category="module"),
            Item(id=2, name="drone", category="drone"),
            Item(id=3, name="launcher", category="module"),
        ]
    )


async def test_add_returns_the_stored_entity(repository: ItemRepository) -> None:
    stored = await repository.add(Item(id=1, name="rig", category="module"))

    assert stored == Item(id=1, name="rig", category="module")


async def test_get_returns_entity_by_primary_key(repository: ItemRepository) -> None:
    await seed(repository)

    assert await repository.get(2) == Item(id=2, name="drone", category="drone")


async def test_get_returns_none_for_unknown_key(repository: ItemRepository) -> None:
    assert await repository.get(404) is None


async def test_find_without_clause_returns_everything(repository: ItemRepository) -> None:
    await seed(repository)

    assert {item.id for item in await repository.find()} == {1, 2, 3}


async def test_find_filters_by_every_set_clause_field(repository: ItemRepository) -> None:
    await seed(repository)

    by_category = await repository.find(ItemClause(category="module"))
    by_both = await repository.find(ItemClause(category="module", name="rig"))

    assert {item.id for item in by_category} == {1, 3}
    assert [item.id for item in by_both] == [1]


async def test_find_ignores_clause_fields_that_are_none(repository: ItemRepository) -> None:
    await seed(repository)

    assert len(await repository.find(ItemClause())) == 3


async def test_find_applies_pagination(repository: ItemRepository) -> None:
    await seed(repository)

    page = await repository.find(page=Page(limit=2, offset=1))

    assert len(page) == 2


async def test_count_respects_clause(repository: ItemRepository) -> None:
    await seed(repository)

    assert await repository.count() == 3
    assert await repository.count(ItemClause(category="module")) == 2
    assert await repository.count(ItemClause(category="unknown")) == 0


async def test_delete_removes_existing_entity(repository: ItemRepository) -> None:
    await seed(repository)

    assert await repository.delete(1) is True
    assert await repository.get(1) is None


async def test_delete_reports_missing_entity(repository: ItemRepository) -> None:
    assert await repository.delete(404) is False
