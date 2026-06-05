"""
V2 Transaction Model — Hybrid storage strategy.

In MongoDB: Grouped sub-objects (pot_dataset_dest, pot_master_id_dp, location)
             + sparse rule_scores (only triggered rules stored).
In API response: Enriched analysis array with categories and details (CPU-only).
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from bson import ObjectId


# Rule categories for API enrichment (not stored in MongoDB)
RULE_CATEGORIES = {
    "var_1": "blacklist", "var_2": "blacklist", "var_3": "blacklist",
    "var_4": "device", "var_5": "blacklist", "var_6": "blacklist",
    "var_7": "blacklist", "var_8": "velocity", "var_9": "behavioral",
    "var_10": "velocity", "var_11": "behavioral", "var_12": "amount",
    "var_13": "velocity", "var_14": "amount", "var_15": "amount",
    "var_16": "amount", "var_17": "amount", "var_18": "amount",
    "var_19": "amount", "var_20": "amount", "var_21": "amount",
    "var_22": "behavioral", "var_23": "blacklist", "var_24": "velocity",
    "var_25": "device", "var_26": "velocity", "var_28": "amount",
    "var_29": "amount", "var_30": "pattern", "var_31": "pattern",
}

# Human-readable rule names for API enrichment
RULE_NAMES = {
    "var_1": "destination_blacklist",
    "var_2": "fraud_cascade_24h",
    "var_3": "email_blacklist",
    "var_4": "risky_device",
    "var_5": "suspicious_merchant",
    "var_6": "gambling_affiliation",
    "var_7": "phone_blacklist",
    "var_8": "velocity_seconds",
    "var_9": "loan_moneyout",
    "var_10": "velocity_days",
    "var_11": "first_time_service",
    "var_12": "amount_vs_limit",
    "var_13": "unusual_time",
    "var_14": "amount_vs_avg",
    "var_15": "amount_balance_ratio",
    "var_16": "repetitive_amount",
    "var_17": "amount_spike",
    "var_18": "cumulative_vs_balance",
    "var_19": "post_prov_cumulative",
    "var_20": "exact_repeat",
    "var_21": "amount_drop",
    "var_22": "unknown_beneficiary",
    "var_23": "compliance_watchlist",
    "var_24": "post_card_change",
    "var_25": "high_risk_device",
    "var_26": "post_provisioning",
    "var_28": "amount_volatility",
    "var_29": "cumulative_sum",
    "var_30": "repetitive_purpose",
    "var_31": "purpose_amount_ratio",
}


class RuleResult(BaseModel):
    """In-memory only — used during scoring, then split into storage + API formats."""
    rule: str              # "var_1" through "var_31"
    triggered: bool
    weight: int            # from config
    score: int             # weight if triggered, 0 otherwise
    details: Dict[str, Any] = Field(default_factory=dict)
    needs_overflow_check: bool = False  # only for var_22


class FraudScore(BaseModel):
    """Stored on every transaction document in MongoDB (sparse).

    rule_scores only contains rules that triggered (non-zero score).
    A clean transaction has rule_scores={} (empty dict).
    """
    final_score: int                    # 0-100 weighted sum
    risk_level: Literal["low", "medium", "high"]
    rule_scores: Dict[str, int]         # {"var_11": 3, "var_22": 5} — only triggered
    triggered_count: int                # count of non-zero scores


class RuleAnalysis(BaseModel):
    """Returned in API response only — NOT stored in MongoDB."""
    rule: str              # "var_8"
    name: str              # "velocity_seconds"
    category: str          # "velocity"
    triggered: bool
    score: int             # weighted score (0 if not triggered)
    details: Dict[str, Any] = Field(default_factory=dict)


class PotDatasetDest(BaseModel):
    """Destination fields from RegionalBank's pot_dataset table."""
    b2: str                            # destination account
    c2: Optional[str] = None           # destination name
    d2: Optional[str] = None           # destination bank
    n2: Optional[str] = None           # merchant/beneficiary description


class PotMasterIdDp(BaseModel):
    """Device context from RegionalBank's pot_master_id_dp table."""
    h1: Optional[str] = None           # device model
    channel: str = "Livin"             # transaction channel


class GeoLocation(BaseModel):
    """GeoJSON Point format for MongoDB geospatial support."""
    type: Literal["Point"] = "Point"
    coordinates: List[float]           # [longitude, latitude]


class TransactionV2(BaseModel):
    """V2 Transaction document model with grouped sub-objects."""
    id: Optional[str] = Field(None, alias="_id")

    # Shard key fields
    customer_id: str
    shard_key_month: str  # YYYY-MM

    # Core transaction fields (top-level for direct index/filter access)
    z1: datetime                       # timestamp
    at3: float                         # amount
    at7: float = 0.0                   # fee
    tp: int = 0                        # purpose code
    b1: Optional[str] = None           # source account
    service: int = 0                   # service code
    service_name: str = ""             # service category
    is_financial: int = 1
    status: str = "SUCCESS"

    # Grouped sub-objects
    pot_dataset_dest: PotDatasetDest   # destination fields
    pot_master_id_dp: PotMasterIdDp    # device context
    location: Optional[GeoLocation] = None  # GeoJSON (null if no coordinates)

    # Fraud scoring (sparse — only triggered rules stored)
    fraud_score: FraudScore

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}

    def to_mongo(self) -> dict:
        data = self.model_dump(by_alias=True, exclude={"id"})
        if self.id:
            data["_id"] = ObjectId(self.id)
        return data

    @classmethod
    def from_mongo(cls, doc: dict) -> "TransactionV2":
        if doc.get("_id"):
            doc["_id"] = str(doc["_id"])
        return cls(**doc)
