from enum import StrEnum
from typing import Literal


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


OrderType = Literal["buy", "sell"]
