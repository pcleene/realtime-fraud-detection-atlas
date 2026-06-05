from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from bson import ObjectId


class GeoPoint(BaseModel):
    """GeoJSON Point for MongoDB 2dsphere queries."""

    type: str = "Point"
    coordinates: List[float]  # [longitude, latitude]

    @classmethod
    def from_coords(cls, lon: float, lat: float) -> "GeoPoint":
        return cls(coordinates=[lon, lat])


class CustomerFeatures(BaseModel):
    """Embedded features for fraud scoring."""

    latest_time_transaction: Optional[datetime] = None
    latest_location: Optional[GeoPoint] = None
    avg_gap_change_password: Optional[float] = None  # days between password changes


class Customer(BaseModel):
    """Customer document model."""

    id: Optional[str] = Field(None, alias="_id")
    customer_id: str
    name: str
    account_ids: List[str] = Field(default_factory=list)  # Optional for projection queries
    province: str
    features: CustomerFeatures = Field(default_factory=CustomerFeatures)
    created_at: Optional[datetime] = None  # Optional for projection queries
    updated_at: Optional[datetime] = None  # Optional for projection queries

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
    def from_mongo(cls, doc: dict) -> "Customer":
        """Create from MongoDB document."""
        if doc.get("_id"):
            doc["_id"] = str(doc["_id"])
        return cls(**doc)
