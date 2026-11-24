import ast
from collections.abc import Iterator
from pathlib import Path


def imports(path: Path) -> Iterator[str]:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            yield node.module or ""
        elif isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)


def test_services_do_not_import_transport_frameworks_or_sqlalchemy() -> None:
    for path in Path("app/domains").glob("*/service.py"):
        for module in imports(path):
            assert not module.startswith(
                ("sqlalchemy", "fastapi", "dishka", "app.infrastructure", "httpx", "asyncpg")
            ), str(path)


def test_manufacturing_calculations_do_not_depend_on_storage_or_transport() -> None:
    for name in ("calculation", "demand", "timing", "filtering", "evaluation"):
        path = Path("app/domains/manufacturing") / (name + ".py")
        for module in imports(path):
            assert not module.startswith(
                ("sqlalchemy", "fastapi", "dishka", "app.infrastructure", "httpx", "asyncpg")
            ), str(path)
            assert not module.endswith((".repository", ".gateway")), str(path)


def test_manufacturing_storage_does_not_import_market_tables() -> None:
    assert "app.domains.market.tables" not in imports(
        Path("app/domains/manufacturing/repository.py")
    )
