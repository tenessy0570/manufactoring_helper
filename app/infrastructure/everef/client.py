from app.infrastructure.http import ResilientHttpClient


class EverefClient(ResilientHttpClient):
    """Transport for EVE Ref reference data (https://ref-data.everef.net)."""
