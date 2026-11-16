"""Imports every domain's tables so Alembic sees them in Base.metadata."""

from app.domains.catalog.tables import ItemTypeTable as ItemTypeTable
