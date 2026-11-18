from dishka import AsyncContainer, Provider, make_async_container

from app.core.config import Settings
from app.core.di.providers import InfrastructureProvider
from app.domains.accounts.providers import AccountProvider
from app.domains.catalog.providers import CatalogProvider
from app.domains.health.providers import HealthProvider
from app.domains.history.providers import HistoryProvider
from app.domains.invention.providers import InventionProvider
from app.domains.manufacturing.providers import ManufacturingProvider
from app.domains.market.providers import MarketProvider
from app.domains.production.providers import ProductionProvider
from app.domains.profiles.providers import ProfileProvider


def create_container(settings: Settings, *extra_providers: Provider) -> AsyncContainer:
    """Builds the application container. Each new domain registers its provider here."""
    return make_async_container(
        InfrastructureProvider(),
        CatalogProvider(),
        MarketProvider(),
        HistoryProvider(),
        ManufacturingProvider(),
        InventionProvider(),
        ProfileProvider(),
        HealthProvider(),
        AccountProvider(),
        ProductionProvider(),
        *extra_providers,
        context={Settings: settings},
    )
