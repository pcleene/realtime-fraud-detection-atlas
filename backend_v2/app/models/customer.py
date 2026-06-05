"""
V2 Customer Model -- Consolidated mega-document.

Embeds data from 12+ relational tables into one MongoDB document.
All field names use RegionalBank's masked names (e1, f1, h1, etc.).
"""

from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from bson import ObjectId


class CustomerFlags(BaseModel):
    """Pre-computed blacklist membership flags (checked at seed/ingest time)."""
    var_3: bool = False    # e1 in pot_be? (email blacklist)
    var_4: bool = False    # h1 in pot_rtd? (risky device)
    var_7: bool = False    # f1 in pot_bmn? (phone blacklist)
    var_25: bool = False   # h1 in pot_rkd? (high-risk device)


class DeviceEntry(BaseModel):
    """Device profile entry from pot_master_id_dp."""
    h1: str                # device model
    r: datetime            # registered date


class LoanIncoming(BaseModel):
    """Recent incoming loan transaction from pot_i."""
    at3: float             # amount
    z1: datetime           # timestamp
    q2: str                # provider name


class CustomerRolling(BaseModel):
    """Rolling/derived fields maintained at scoring time."""
    z1_prev: Optional[datetime] = None      # last transaction time
    at3_prev: Optional[float] = None        # last amount
    at3_prev2: Optional[float] = None       # second-last amount
    pt_latest: Optional[datetime] = None    # last provisioning time
    w2_latest: Optional[datetime] = None    # last card change time
    w1_latest: Optional[int] = None         # last card change type
    z3: Optional[int] = None                # typical hour lower
    z4: Optional[int] = None                # typical hour upper
    bl: Optional[float] = None              # current balance
    b1: Optional[str] = None                # primary account
    at3_recent: List[float] = Field(default_factory=list)  # last N amounts
    tp_recent: List[int] = Field(default_factory=list)     # last N purpose codes
    at3_sum: float = 0.0                    # sum in current window
    at6: float = 0.0                        # std dev in current window
    bl_window_start: Optional[float] = None # balance at window start
    window_start: Optional[datetime] = None # window start time
    pot_i_recent: List[LoanIncoming] = Field(default_factory=list)  # recent loan incoming


class CustomerV2(BaseModel):
    """V2 Customer document -- consolidated from 12+ relational tables."""
    customer_id: Optional[str] = None       # business key (shard key)
    e1: Optional[str] = None                # email (from pot_master_id)
    f1: Optional[str] = None                # phone (from pot_master_id)
    r: Optional[datetime] = None            # registration date
    y: Optional[str] = None                 # segment (PB/PL/PR)
    pot_master_id_dp: List[DeviceEntry] = Field(default_factory=list)
    flags: CustomerFlags = Field(default_factory=CustomerFlags)
    av1: Optional[float] = None             # volatility threshold (from pot_btv)
    av2: Optional[float] = None             # cumulative sum threshold (from pot_btvs)
    service_ever: List[int] = Field(default_factory=list)
    b24_count: int = 0                      # total known beneficiaries
    b24_list: List[str] = Field(default_factory=list)  # embedded beneficiary accounts (max 500)
    rolling: CustomerRolling = Field(default_factory=CustomerRolling)

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}

    def to_mongo(self) -> dict:
        data = self.model_dump(exclude={"customer_id"})
        if self.customer_id:
            data["customer_id"] = self.customer_id
        return data

    @classmethod
    def from_mongo(cls, doc: dict) -> "CustomerV2":
        if doc is None:
            raise ValueError("Customer document is None")
        # Drop _id (ObjectId) — we use customer_id as the business key
        doc.pop("_id", None)
        # Handle nested rolling dict
        if "rolling" in doc and isinstance(doc["rolling"], dict):
            if "pot_i_recent" in doc["rolling"]:
                doc["rolling"]["pot_i_recent"] = [
                    LoanIncoming(**item) if isinstance(item, dict) else item
                    for item in doc["rolling"]["pot_i_recent"]
                ]
        return cls(**doc)
