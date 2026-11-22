"""Imports every domain's tables so Alembic sees them in Base.metadata."""

from app.domains.accounts.tables import SessionTable as SessionTable
from app.domains.accounts.tables import UserTable as UserTable
from app.domains.catalog.tables import ItemTypeTable as ItemTypeTable
from app.domains.exclusions import tables as _exclusions  # noqa: F401
from app.domains.history.tables import HistoryDayTable as HistoryDayTable
from app.domains.history.tables import HistoryStateTable as HistoryStateTable
from app.domains.invention.tables import InventionPlanTable as InventionPlanTable
from app.domains.invention.tables import InventionRequestTable as InventionRequestTable
from app.domains.manufacturing.tables import RecipeTable as RecipeTable
from app.domains.market.tables import MarketPriceTable as MarketPriceTable
from app.domains.market.tables import MarketStateTable as MarketStateTable
from app.domains.production.tables import ProductionTable as ProductionTable
from app.domains.profiles.tables import ProfileDefaultTable as ProfileDefaultTable
from app.domains.profiles.tables import ProfileTable as ProfileTable
from app.domains.trading.tables import TradeMetadataTable as TradeMetadataTable
