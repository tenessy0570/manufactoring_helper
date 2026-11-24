from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.opportunities import OpportunitySettings


class ProfileSettings(OpportunitySettings):
    model_config = ConfigDict(extra="forbid")
    offset: Literal[0] = 0


class ProfileName(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Profile name must not be blank")
        return value


class ProfileCreate(ProfileName):
    settings: ProfileSettings = Field(default_factory=ProfileSettings)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    settings: ProfileSettings | None = None

    @model_validator(mode="after")
    def validate_update(self) -> "ProfileUpdate":
        if "name" in self.model_fields_set:
            if self.name is None or not self.name.strip():
                raise ValueError("Profile name must not be blank")
            self.name = self.name.strip()
        if "settings" in self.model_fields_set and self.settings is None:
            raise ValueError("Profile settings cannot be null")
        return self


class Profile(BaseModel):
    id: UUID
    name: str
    settings: ProfileSettings
    created_at: datetime
    updated_at: datetime
    is_default: bool = False


class ProfilePage(BaseModel):
    items: list[Profile]
    default_profile_id: UUID
