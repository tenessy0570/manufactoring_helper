from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr


class User(BaseModel):
    id: UUID
    username: str
    is_superuser: bool = False
    is_active: bool = True
    created_at: datetime


class StoredUser(User):
    password_hash: str


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: SecretStr = Field(min_length=1, max_length=128)


class UserCreate(Credentials):
    password: SecretStr = Field(min_length=12, max_length=128)
    is_superuser: bool = False


class UserUpdate(BaseModel):
    is_active: bool | None = None
    password: SecretStr | None = Field(default=None, min_length=12, max_length=128)


class PasswordChange(BaseModel):
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=12, max_length=128)
