from abc import ABC, abstractmethod

from app.domains.trading.models import TradeTypeDetails
from app.infrastructure.everef import EverefClient


class TradingGateway(ABC):
    @abstractmethod
    async def type_details(self, type_id: int) -> TradeTypeDetails: ...


class EverefTradingGateway(TradingGateway):
    def __init__(self, everef: EverefClient) -> None:
        self._everef = everef

    async def type_details(self, type_id: int) -> TradeTypeDetails:
        data = await self._everef.get_json(f"/types/{type_id}")
        name = data.get("name")
        if isinstance(name, dict):
            data = {**data, "name": name.get("en")}
        return TradeTypeDetails.model_validate(data)
