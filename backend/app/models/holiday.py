from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from bson import ObjectId


class DateRange(BaseModel):
    """Date range for holidays."""

    start: datetime
    end: datetime


class Holiday(BaseModel):
    """Holiday document model."""

    id: Optional[str] = Field(None, alias="_id")
    name: str
    description: str
    date_range: DateRange
    is_cuti_bersama: bool
    year: int

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}

    def to_mongo(self) -> dict:
        """Convert to MongoDB document."""
        data = self.model_dump(by_alias=True, exclude={"id"})
        if self.id:
            data["_id"] = ObjectId(self.id)
        return data

    @classmethod
    def from_mongo(cls, doc: dict) -> "Holiday":
        """Create from MongoDB document."""
        if doc.get("_id"):
            doc["_id"] = str(doc["_id"])
        return cls(**doc)
