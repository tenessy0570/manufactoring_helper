"""Capture public invention output and skill parameter names for reproducible tests."""

import asyncio
import json
from pathlib import Path

import httpx

from app.domains.invention.gateway import ENCRYPTION_SKILLS, SCIENCE_SKILLS, EverefInventionGateway
from app.domains.invention.models import InventionSettings
from app.domains.manufacturing.gateway import IndustryClient


async def main() -> None:
    async with httpx.AsyncClient(timeout=45, headers={"User-Agent": "eve-manufacturing"}) as http:
        params: dict[str, str | int] = {name: 5 for name in SCIENCE_SKILLS}
        params.update({name: 4 for name in ENCRYPTION_SKILLS})
        params.update({"product_id": 2456, "runs": 1, "me": 0, "te": 0})
        response = await http.get("https://api.everef.net/v1/industry/cost", params=params)
        response.raise_for_status()
        data = response.json()
        path = Path("tests/fixtures/invention.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_text, json.dumps(data, indent=2), encoding="utf-8")
        print("Public invention fixture saved")
        ids = await http.post(
            "https://esi.evetech.net/universe/ids/",
            json=[
                "Accelerant Decryptor",
                "Attainment Decryptor",
                "Augmentation Decryptor",
                "Optimized Attainment Decryptor",
                "Optimized Augmentation Decryptor",
                "Parity Decryptor",
                "Process Decryptor",
                "Symmetry Decryptor",
            ],
        )
        ids.raise_for_status()
        print("DECRYPTORS", json.dumps(ids.json().get("inventory_types")))
    async with httpx.AsyncClient(
        base_url="https://api.everef.net", timeout=45, headers={"User-Agent": "eve-manufacturing"}
    ) as http:
        gateway = EverefInventionGateway(IndustryClient(http, 3, 1))
        plans = await gateway.fetch(InventionSettings(type_id=2456))
        path = Path("tests/fixtures/invention-plans.json")
        await asyncio.to_thread(
            path.write_text,
            json.dumps([plan.model_dump(mode="json") for plan in plans], indent=2),
            encoding="utf-8",
        )
        print("Validated options:", len(plans))
        for plan in plans:
            print(plan.decryptor_name, plan.probability, plan.runs_per_copy, plan.units_per_run)


if __name__ == "__main__":
    asyncio.run(main())
