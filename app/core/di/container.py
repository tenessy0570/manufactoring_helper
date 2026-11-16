from dishka import AsyncContainer, Provider, make_async_container

from app.core.config import Settings
from app.core.di.providers import InfrastructureProvider
from app.domains.catalog.providers import CatalogProvider
from app.domains.health.providers import HealthProvider


def create_container(settings: Settings, *extra_providers: Provider) -> AsyncContainer:
    """Builds the application container. Each new domain registers its provider here."""
    return make_async_container(
        InfrastructureProvider(),
        CatalogProvider(),
        HealthProvider(),
        *extra_providers,
        context={Settings: settings},
    )
