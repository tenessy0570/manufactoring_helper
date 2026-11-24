import json
import re
from pathlib import Path

import httpx

from app.main import create_app
from tests.helpers import make_settings


async def test_browser_config_exposes_only_public_values() -> None:
    app = create_app(
        settings=make_settings(
            postgres_password="private-database-marker", redis_password="private-redis-marker"
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get("/ui/config.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    payload = response.text.removeprefix("window.eveConfig = Object.freeze(").removesuffix(");")
    assert json.loads(payload) == {
        "marketFreshnessMs": 1200000,
        "freshnessPollMs": 60000,
        "clockTickMs": 30000,
        "searchDebounceMs": 250,
    }
    assert "private-" not in response.text


def test_public_files_contain_no_embedded_credentials() -> None:
    patterns = (
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"(?:postgres(?:ql)?|redis)(?:\+asyncpg)?://[^\s/]+:[^\s@]+@",
        r"AKIA[0-9A-Z]{16}",
        r"gh[pousr]_[A-Za-z0-9]{36,}",
        r"(?i)(?:api[_-]?key|client[_-]?secret|password)\s*[:=]\s*['\"][^'\"\s+<>]{8,}['\"]",
    )
    for root in (Path("app/web/static"), Path("app/web/templates")):
        for path in root.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                assert not any(re.search(pattern, text) for pattern in patterns), str(path)
