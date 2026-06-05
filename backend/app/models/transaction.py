from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from bson import ObjectId

from app.models.customer import GeoPoint


class TransactionCustomerRef(BaseModel):
    """Extended reference to customer (denormalized)."""

    _id: Optional[str] = None
    customer_id: str
    name: str


class TransactionMerchant(BaseModel):
    """Merchant information."""

    id: str
    name: str
    mcc: str
    category: str  # marketplace, food_delivery, ride_hailing, retail, telco, utilities


class TransactionDevice(BaseModel):
    """Device information."""

    device_id: str
    device_type: str  # ios, android, web
    ip: str


class RuleAnalysis(BaseModel):
    """Individual rule analysis result."""

    rule: str
    score: int
    triggered: bool
    details: Optional[Dict[str, Any]] = None


class FraudScore(BaseModel):
    """Fraud scoring result."""

    final_score: int
    risk_level: Literal["low", "medium", "high"]
    analysis: List[RuleAnalysis]


class Transaction(BaseModel):
    """Transaction document model."""

    id: Optional[str] = Field(None, alias="_id")

    # Shard key fields
    customer_id: str
    shard_key_month: str  # YYYY-MM

    # Extended references
    customer: TransactionCustomerRef
    account_id: str

    # Transaction details
    type: Literal["debit", "credit"]
    channel: Literal["Livin", "KOPRA", "ATM", "QRIS", "Branch", "Ecom"]
    amount: float
    currency: str = "IDR"
    status: Literal["authorized", "captured", "reversed", "declined"]
    timestamp: datetime

    # Location
    location: Optional[GeoPoint] = None
    city: Optional[str] = None
    province: Optional[str] = None

    # Merchant and device
    merchant: TransactionMerchant
    device: TransactionDevice

    # Fraud scoring
    fraud_score: Optional[FraudScore] = None

    # Extensibility
    attrs: Dict[str, Any] = Field(default_factory=dict)

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
    def from_mongo(cls, doc: dict) -> "Transaction":
        """Create from MongoDB document."""
        if doc.get("_id"):
            doc["_id"] = str(doc["_id"])
        return cls(**doc)
