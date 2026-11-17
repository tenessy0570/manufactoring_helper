"""Merge fee variants and reuse saved invention estimates without taxes or source calls."""

import copy
import hashlib
import json
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None


def tax_free_result(payload: dict[str, Any] | None, settings: dict[str, Any]) -> Any:
    if payload is None:
        return None
    result = copy.deepcopy(payload)
    factor = (
        1 + Decimal(str(settings.get("broker_fee", 0))) / 100
        if settings.get("order_type", "sell") == "buy"
        else Decimal(1)
    )
    available = []
    for option in result["options"]:
        if option["cost_per_attempt"] is None:
            continue
        plan = option["plan"]
        cost = (
            Decimal(option["cost_per_attempt"]) - Decimal(plan["job_cost_per_attempt"])
        ) / factor
        unit_cost = cost / (
            Decimal(plan["probability"]) * plan["runs_per_copy"] * plan["units_per_run"]
        )
        option["cost_per_attempt"] = str(cost)
        option["expected_cost_per_unit"] = str(unit_cost)
        available.append(option)
    result["best"] = (
        min(available, key=lambda value: Decimal(value["expected_cost_per_unit"]))
        if available
        else None
    )
    return result


def score(value: dict[str, Any]) -> tuple[bool, str]:
    return value["status"] == "ready", str(value["updated_at"])


def upgrade() -> None:
    bind = op.get_bind()
    table = sa.Table("invention_requests", sa.MetaData(), autoload_with=bind)
    canonical: dict[str, dict[str, Any]] = {}
    for row in bind.execute(sa.select(table)).mappings():
        old_settings = row["settings"]
        settings = {
            "type_id": old_settings["type_id"],
            "hub_id": old_settings.get("hub_id", "jita"),
            "order_type": old_settings.get("order_type", "sell"),
        }
        key_data = {**settings, "science_level": 5, "encryption_level": 4, "broker_fee": "0"}
        key = hashlib.sha256(json.dumps(key_data, sort_keys=True).encode()).hexdigest()
        candidate = dict(row)
        candidate.update(
            key=key, settings=settings, result=tax_free_result(row["result"], old_settings)
        )
        previous = canonical.get(key)

        if previous is None or score(candidate) > score(previous):
            canonical[key] = candidate
    if canonical:
        bind.execute(sa.delete(table))
        bind.execute(sa.insert(table), list(canonical.values()))


def downgrade() -> None:
    # Source plans and usable estimates remain intact; discarded fee variants are not recreated.
    pass
