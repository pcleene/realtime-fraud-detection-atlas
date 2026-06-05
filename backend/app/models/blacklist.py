from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field
from bson import ObjectId

from app.models.customer import GeoPoint


class BlacklistLocation(BaseModel):
    """Blacklist location document model."""

    id: Optional[str] = Field(None, alias="_id")
    address: str
    city: str
    province: str
    location: GeoPoint
    category: Literal["fraud_hub", "scammer", "wifi", "merchant"]
    normalized: List[str] = Field(default_factory=list)  # Optional tokens for similarity
    added_at: datetime = Field(default_factory=datetime.utcnow)
    added_reason: str

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
    def from_mongo(cls, doc: dict) -> "BlacklistLocation":
        """Create from MongoDB document."""
        if doc.get("_id"):
            doc["_id"] = str(doc["_id"])
        return cls(**doc)
