from pydantic import BaseModel, Field


class ExcludedItem(BaseModel):
    type_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=300)


class ExclusionList(BaseModel):
    items: list[ExcludedItem] = Field(default_factory=list, max_length=1000)
