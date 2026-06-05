# Mock data generation API for frontend testing
# Generates realistic test data without hitting the database

import random
import secrets
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Query, Depends
from pydantic import BaseModel

# Import seed data generators
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from seed.data.indonesian_names import generate_indonesian_name
from seed.data.provinces import (
    weighted_choice_province,
    get_city_for_province,
    generate_province_coords,
    PROVINCE_DISTRIBUTION,
)
from seed.data.merchants import (
    get_merchant_for_channel,
    weighted_choice_channel,
    generate_amount,
)
from seed.data.devices import (
    generate_device_fingerprint,
    generate_indonesian_ip,
)
from seed.data.profiles import (
    CustomerSegment,
    select_segment,
    SEGMENT_PROFILES,
)
from seed.data.fraud_scenarios import (
    FraudType,
    FRAUD_HOTSPOTS,
)

router = APIRouter(prefix="/mock", tags=["mock"])


class MockCustomer(BaseModel):
    """Generated mock customer."""
    customer_id: str
    name: str
    gender: str
    province: str
    city: str
    segment: str
    account_ids: List[str]


class MockTransaction(BaseModel):
    """Generated mock transaction request."""
    customer_id: str
    account_id: str
    amount: float
    lat: float
    lon: float
    timestamp: str
    channel: str
    merchant_id: str
    merchant_name: str
    mcc: str
    device_id: str
    device_type: str
    ip: str
    # Metadata for testing
    _fraud_type: Optional[str] = None
    _expected_score_range: Optional[str] = None


class MockDataResponse(BaseModel):
    """Response containing mock data."""
    customer: MockCustomer
    transaction: MockTransaction
    notes: List[str]


class MockBatchResponse(BaseModel):
    """Response containing batch of mock data."""
    count: int
    items: List[MockDataResponse]


def generate_customer_id() -> str:
    """Generate random customer ID."""
    return f"CUST-{secrets.token_hex(6).upper()}"


def generate_account_id() -> str:
    """Generate random account ID."""
    return f"ACC-{secrets.token_hex(4).upper()}"


@router.get("/customer", response_model=MockCustomer)
async def generate_mock_customer(
    province: Optional[str] = Query(None, description="Specific province"),
    segment: Optional[str] = Query(None, description="Customer segment (mass_market, affluent, student, etc.)"),
):
    """
    Generate a realistic mock customer.

    Use this to get test customer data for the scoring API.
    """
    if province is None:
        province = weighted_choice_province()

    if segment:
        try:
            seg = CustomerSegment(segment)
        except ValueError:
            seg = select_segment()
    else:
        seg = select_segment()

    city, _, _ = get_city_for_province(province)
    name, gender = generate_indonesian_name(province=province)

    # Generate 1-3 accounts
    num_accounts = random.choices([1, 2, 3], weights=[0.7, 0.25, 0.05])[0]
    account_ids = [generate_account_id() for _ in range(num_accounts)]

    return MockCustomer(
        customer_id=generate_customer_id(),
        name=name,
        gender=gender,
        province=province,
        city=city,
        segment=seg.value,
        account_ids=account_ids,
    )


@router.get("/transaction", response_model=MockDataResponse)
async def generate_mock_transaction(
    fraud_type: Optional[str] = Query(None, description="Inject fraud: velocity, impossible_travel, blacklist"),
    province: Optional[str] = Query(None, description="Customer province"),
    channel: Optional[str] = Query(None, description="Transaction channel: Livin, QRIS, ATM, etc."),
    amount_range: Optional[str] = Query(None, description="Amount range: small, medium, large, xlarge"),
):
    """
    Generate a realistic mock transaction with customer.

    This endpoint generates both a customer and a transaction request
    that can be directly used with POST /score-transaction.

    Fraud types available for testing:
    - velocity: Rapid transaction (use with previous transaction)
    - impossible_travel: Far location in short time
    - blacklist: Near fraud hotspot
    """
    notes = []

    # Generate customer
    if province is None:
        province = weighted_choice_province()
    city, base_lon, base_lat = get_city_for_province(province)
    name, gender = generate_indonesian_name(province=province)
    customer_id = generate_customer_id()
    account_ids = [generate_account_id()]

    customer = MockCustomer(
        customer_id=customer_id,
        name=name,
        gender=gender,
        province=province,
        city=city,
        segment=select_segment().value,
        account_ids=account_ids,
    )

    # Generate transaction
    if channel is None:
        channel = weighted_choice_channel()

    merchant, category = get_merchant_for_channel(channel)

    # Handle fraud injection
    fraud_label = None
    expected_score = None

    if fraud_type == "velocity":
        # For velocity, timestamp should be very recent
        timestamp = datetime.utcnow() - timedelta(seconds=random.randint(2, 8))
        coords = generate_province_coords(province, precision="district")
        notes.append("Velocity fraud: Submit immediately after a previous transaction")
        notes.append("Expected to trigger: velocity rule (+20 points)")
        fraud_label = "velocity"
        expected_score = "20-40"

    elif fraud_type == "impossible_travel":
        # For impossible travel, use far location
        far_provinces = ["Papua", "Sumatera Utara", "Sulawesi Selatan"]
        far_province = random.choice([p for p in far_provinces if p != province])
        coords = generate_province_coords(far_province, precision="city")
        timestamp = datetime.utcnow()
        notes.append(f"Impossible travel: Location in {far_province} (far from {province})")
        notes.append("Submit within 30 minutes of previous transaction for detection")
        notes.append("Expected to trigger: impossible_travel rule (+30 points)")
        fraud_label = "impossible_travel"
        expected_score = "30-50"

    elif fraud_type == "blacklist":
        # Use coordinates near a fraud hotspot
        hotspot = random.choice(FRAUD_HOTSPOTS)
        coords = [
            hotspot["coords"][0] + random.uniform(-0.002, 0.002),
            hotspot["coords"][1] + random.uniform(-0.002, 0.002),
        ]
        timestamp = datetime.utcnow()
        notes.append(f"Blacklist proximity: Near {hotspot['category']} hotspot in {hotspot['city']}")
        notes.append("Expected to trigger: blacklist_proximity rule (+10-35 points)")
        fraud_label = "blacklist"
        expected_score = "10-35"

    else:
        # Normal transaction
        coords = generate_province_coords(province, precision="precise")
        timestamp = datetime.utcnow()
        notes.append("Normal transaction - low fraud risk expected")
        expected_score = "0-15"

    # Generate amount
    if amount_range == "small":
        amount = random.randint(5_000, 50_000)
    elif amount_range == "medium":
        amount = random.randint(50_000, 500_000)
    elif amount_range == "large":
        amount = random.randint(500_000, 5_000_000)
    elif amount_range == "xlarge":
        amount = random.randint(5_000_000, 50_000_000)
    else:
        amount = generate_amount(channel=channel, category=category)

    # Generate device
    device = generate_device_fingerprint()
    ip = generate_indonesian_ip()

    transaction = MockTransaction(
        customer_id=customer_id,
        account_id=account_ids[0],
        amount=amount,
        lat=coords[1],
        lon=coords[0],
        timestamp=timestamp.isoformat() + "Z",
        channel=channel,
        merchant_id=merchant["id"],
        merchant_name=merchant["name"],
        mcc=merchant["mcc"],
        device_id=device["device_id"],
        device_type=device["device_type"],
        ip=ip,
        _fraud_type=fraud_label,
        _expected_score_range=expected_score,
    )

    return MockDataResponse(
        customer=customer,
        transaction=transaction,
        notes=notes,
    )


@router.get("/batch", response_model=MockBatchResponse)
async def generate_mock_batch(
    count: int = Query(10, ge=1, le=100, description="Number of transactions to generate"),
    fraud_rate: float = Query(0.12, ge=0, le=1, description="Fraction of fraudulent transactions"),
):
    """
    Generate a batch of mock transactions.

    Useful for load testing or generating test datasets.
    """
    items = []

    for i in range(count):
        # Determine if this should be fraudulent
        if random.random() < fraud_rate:
            fraud_type = random.choice(["velocity", "impossible_travel", "blacklist"])
        else:
            fraud_type = None

        # Generate transaction
        result = await generate_mock_transaction(fraud_type=fraud_type)
        items.append(result)

    return MockBatchResponse(
        count=len(items),
        items=items,
    )


@router.get("/provinces")
async def list_provinces():
    """List available provinces with their distribution weights."""
    return {
        "provinces": [
            {"name": name, "weight": weight}
            for name, weight in sorted(
                PROVINCE_DISTRIBUTION.items(),
                key=lambda x: x[1],
                reverse=True
            )
        ]
    }


@router.get("/channels")
async def list_channels():
    """List available transaction channels."""
    return {
        "channels": [
            {"name": "Livin", "description": "Mobile banking app", "weight": 0.40},
            {"name": "QRIS", "description": "QR code payments", "weight": 0.25},
            {"name": "ATM", "description": "ATM transactions", "weight": 0.15},
            {"name": "KOPRA", "description": "Corporate banking", "weight": 0.10},
            {"name": "Branch", "description": "Branch transactions", "weight": 0.07},
            {"name": "Ecom", "description": "E-commerce", "weight": 0.03},
        ]
    }


@router.get("/fraud-types")
async def list_fraud_types():
    """List available fraud types for testing."""
    return {
        "fraud_types": [
            {
                "name": "velocity",
                "description": "Rapid sequential transactions (<10 seconds apart)",
                "detection_rule": "velocity",
                "points": 20,
            },
            {
                "name": "impossible_travel",
                "description": "Location change faster than 800 km/h",
                "detection_rule": "impossible_travel",
                "points": 30,
            },
            {
                "name": "blacklist",
                "description": "Transaction near known fraud hotspot",
                "detection_rule": "blacklist_proximity",
                "points": "10-35 (varies by category)",
            },
        ]
    }


@router.get("/segments")
async def list_customer_segments():
    """List customer segments with their characteristics."""
    segments = []
    for segment, profile in SEGMENT_PROFILES.items():
        segments.append({
            "name": segment.value,
            "age_range": profile["age_range"],
            "monthly_txn_count": profile["monthly_txn_count"],
            "avg_txn_amount_idr": profile["avg_txn_amount_idr"],
            "primary_channels": profile["primary_channels"],
            "fraud_risk": profile["fraud_risk"],
        })
    return {"segments": segments}


# Debug endpoint to get a real customer from DB
from app.db import get_db

@router.get("/real-customer")
async def get_real_customer(db=Depends(get_db)):
    """Get a real customer from the database for testing."""
    customer = await db.customers.find_one()
    if not customer:
        return {"error": "No customers in database"}
    return {
        "customer_id": customer.get("customer_id"),
        "accounts": [a.get("account_id") for a in customer.get("accounts", [])],
        "devices": [d.get("device_id") for d in customer.get("devices", [])],
    }


@router.get("/customers")
async def get_customers(limit: int = Query(100000, ge=1, le=500000), db=Depends(get_db)):
    """
    Get a list of real customer IDs from the database for load testing.

    For realistic load testing, use 100K+ customers to avoid triggering
    velocity rules on every transaction (threshold: 10 seconds between txns).

    Memory: 100K customers × ~20 bytes = ~2MB (trivial)
    """
    cursor = db.customers.find({}, {"customer_id": 1, "_id": 0}).limit(limit)
    customers = await cursor.to_list(length=limit)
    return {
        "customers": customers,
        "count": len(customers)
    }
