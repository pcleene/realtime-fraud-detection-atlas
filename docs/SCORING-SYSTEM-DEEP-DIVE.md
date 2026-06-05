# Fraud Scoring System - Complete Technical Deep Dive

This document provides a comprehensive, step-by-step explanation of how the fraud scoring system works, from the moment a transaction request arrives to the final risk assessment.

## Table of Contents

1. [Overview](#1-overview)
2. [The Complete Request Flow](#2-the-complete-request-flow)
3. [Database Operations (The Hot Path)](#3-database-operations-the-hot-path)
4. [Fraud Rules - Detailed Explanation](#4-fraud-rules---detailed-explanation)
5. [Score Aggregation & Risk Classification](#5-score-aggregation--risk-classification)
6. [Code Walkthrough](#6-code-walkthrough)
7. [Data Flow Diagram](#7-data-flow-diagram)
8. [Mock Data Generator](#8-mock-data-generator)
9. [Configuration Reference](#9-configuration-reference)
10. [Performance Analysis](#10-performance-analysis)

---

## 1. Overview

### What Does This System Do?

The fraud scoring system evaluates every incoming transaction and assigns a **risk score from 0 to 100**. This score represents how likely the transaction is fraudulent based on multiple behavioral signals.

### The Core Concept

```
Transaction Request → 5 Fraud Rules → Combined Score → Risk Level
                          ↓
                    [0-39: Low]
                    [40-69: Medium]
                    [70-100: High]
```

### The Five Fraud Rules

| Rule | What It Detects | Max Points |
|------|-----------------|------------|
| **Velocity** | Transactions happening too fast (bot behavior) | 20 |
| **Impossible Travel** | Being in two far places too quickly (stolen credentials) | 30 |
| **Blacklist Proximity** | Transaction near known fraud locations | 35 |
| **Password Frequency** | Account with suspicious password change patterns | 15 |
| **Holiday** | Transaction during high-fraud-risk periods | 10 |

**Maximum possible score: 110 (capped at 100)**

---

## 2. The Complete Request Flow

Let's follow a transaction from start to finish:

### Step 1: API Receives Request

```
POST /score-transaction
```

**Input payload:**
```json
{
  "customer_id": "CUST-7F3A2B1C9E4D",
  "account_id": "ACC-7A8B9C0D",
  "amount": 1500000,
  "lat": -6.2088,
  "lon": 106.8456,
  "timestamp": "2025-12-10T10:03:10Z",
  "channel": "Livin",
  "merchant_id": "M-TOKO001",
  "merchant_name": "Tokopedia",
  "mcc": "5311",
  "device_id": "android_75ee86bb8ebb445e",
  "device_type": "android",
  "ip": "<private-ip>"
}
```

### Step 2: Validation

The API validates:
- `customer_id` format: Must match `CUST-XXXXXXXXXXXX` (12 hex characters)
- `channel`: Must be one of `Livin`, `KOPRA`, `ATM`, `QRIS`, `Branch`, `Ecom`
- `device_type`: Must be one of `ios`, `android`, `web`
- All required fields present

**File:** `backend/app/routes/score.py`

```python
CUSTOMER_ID_PATTERN = re.compile(r"^CUST-[A-F0-9]{12}$")

if not CUSTOMER_ID_PATTERN.match(request.customer_id):
    raise HTTPException(status_code=400, ...)
```

### Step 3: Fraud Scoring Service Takes Over

**File:** `backend/app/services/fraud.py`

The `FraudScoringService.score_transaction()` method orchestrates everything:

```python
async def score_transaction(self, request: ScoreTransactionRequest):
    # 1. Fetch customer from database
    # 2. Run all 5 fraud rules (SCORING PHASE)
    # 3. Calculate final score
    # 4. Update customer features (PERSISTENCE PHASE)
    # 5. Store transaction with score
    # 6. Return result with separate timing metrics
```

### Step 4: Response Sent

```json
{
  "transaction_id": "675f1a2b3c4d5e6f7a8b9c0d",
  "risk_score": 35,
  "risk_level": "low",
  "analysis": [...],
  "scoring_time_ms": 12.34,
  "persistence_time_ms": 8.76,
  "total_time_ms": 21.10,
  "recorded_at": "2025-12-10T10:03:10.456Z"
}
```

**Note:** The response separates timing into:
- `scoring_time_ms`: Time for rules evaluation (steps 1-3)
- `persistence_time_ms`: Time for database writes (steps 4-5)
- `total_time_ms`: End-to-end processing time

---

## 3. Database Operations (The Hot Path)

The "hot path" is the critical performance path that must complete in <50ms. It consists of exactly **5 database operations**:

### Operation 1: Fetch Customer (READ)

**Purpose:** Get customer data including their embedded features for fraud analysis.

**Collection:** `customers`

```python
customer_doc = self.db.customers.find_one(
    {"customer_id": request.customer_id}
)
```

**What we get:**
```javascript
{
  customer_id: "CUST-7F3A2B1C9E4D",
  name: "Budi Santoso",
  account_ids: ["ACC-7A8B9C0D"],  // Simplified to array of IDs
  province: "DKI Jakarta",
  features: {
    latest_time_transaction: ISODate("2025-12-10T09:00:00Z"),  // Last txn time
    latest_location: { type: "Point", coordinates: [106.8, -6.2] },  // Last txn location
    avg_gap_change_password: 45.5  // Days between password changes
  }
}
```

**Why embedded features?**
- Single read gets everything needed
- No joins or additional queries
- Features are updated atomically with each transaction

**Time budget:** <5ms

### Operation 2: Blacklist Proximity Check (READ)

**Purpose:** Check if transaction location is near known fraud hotspots.

**Collection:** `blacklist_locations`

```python
nearby = db.blacklist_locations.find_one({
    "location": {
        "$nearSphere": {
            "$geometry": {
                "type": "Point",
                "coordinates": [lon, lat]
            },
            "$maxDistance": 500  # meters
        }
    }
})
```

**How `$nearSphere` works:**
1. Uses MongoDB's 2dsphere geospatial index
2. Finds documents with `location` within 500 meters of the transaction
3. Returns the nearest one (if any) - no distance calculation needed in Python

**Time budget:** <5ms

### Operation 3: Holiday Check (READ)

**Purpose:** Check if transaction occurs during a holiday period.

**Collection:** `holidays`

```python
holiday = db.holidays.find_one({
    "date_range.start": {"$lte": txn_date},
    "date_range.end": {"$gte": txn_date}
})
```

**How the date range query works:**
- Transaction date must be >= holiday start AND <= holiday end
- Index on `(date_range.start, date_range.end)` makes this fast

**Example match:**
```javascript
// Transaction: 2025-04-01
// Holiday document:
{
  name: "Idul Fitri",
  date_range: {
    start: ISODate("2025-03-30"),  // 2025-04-01 >= this ✓
    end: ISODate("2025-04-04")     // 2025-04-01 <= this ✓
  },
  is_cuti_bersama: true
}
```

**Time budget:** <2ms

### Operation 4: Update Customer Features (WRITE)

**Purpose:** Update customer's features for the next transaction's analysis.

**Collection:** `customers`

```python
self.db.customers.update_one(
    {"customer_id": request.customer_id},
    {"$set": {
        "features.latest_time_transaction": request.timestamp,
        "features.latest_location": {
            "type": "Point",
            "coordinates": [lon, lat]
        },
        "updated_at": datetime.utcnow()
    }}
)
```

**Why this matters:**
- Next transaction will compare against THIS transaction's time/location
- Enables velocity and impossible travel checks

**Time budget:** <5ms

### Operation 5: Insert Transaction (WRITE)

**Purpose:** Store the scored transaction for audit trail and analytics.

**Collection:** `transactions`

```python
result = self.db.transactions.insert_one(transaction.to_mongo())
```

**What gets stored:**
```javascript
{
  customer_id: "CUST-7F3A2B1C9E4D",
  shard_key_month: "2025-12",  // For sharding
  customer: { _id, customer_id, name },  // Denormalized
  account_id: "ACC-7A8B9C0D",  // Simplified: just the ID
  amount: 1500000,
  channel: "Livin",
  timestamp: ISODate("2025-12-10T10:03:10Z"),
  location: { type: "Point", coordinates: [106.8456, -6.2088] },
  device: {
    device_id: "android_75ee86bb8ebb445e",
    device_type: "android",
    device_model: "Galaxy A54",
    os_version: "13",
    ip: "<private-ip>"
  },
  fraud_score: {
    final_score: 35,
    risk_level: "low",
    analysis: [
      { rule: "velocity", score: 0, triggered: false, details: {...} },
      { rule: "impossible_travel", score: 0, triggered: false, details: {...} },
      { rule: "blacklist_proximity", score: 35, triggered: true, details: {...} },
      { rule: "password_frequency", score: 0, triggered: false, details: {...} },
      { rule: "holiday", score: 0, triggered: false, details: {...} }
    ]
  },
  fraud_metadata: null  // or { injected_type, expected_rules } for test data
}
```

**Time budget:** <5ms

---

## 4. Fraud Rules - Detailed Explanation

### Rule 1: Velocity Check

**File:** `backend/app/services/rules/velocity.py`

**Purpose:** Detect automated/bot transactions by checking if transactions are happening too fast.

**Logic:**
```
IF (current_time - last_transaction_time) < 10 seconds
THEN add 20 points to risk score
```

**Implementation:**
```python
def check_velocity(
    latest_time_transaction: Optional[datetime],
    current_timestamp: datetime,
) -> RuleAnalysis:

    # No previous transaction? No velocity issue.
    if latest_time_transaction is None:
        return RuleAnalysis(rule="velocity", score=0, triggered=False, ...)

    # Calculate time since last transaction
    delta_seconds = (current_timestamp - latest_time_transaction).total_seconds()

    # Check against threshold (default: 10 seconds)
    if delta_seconds < settings.min_txn_gap_seconds:
        return RuleAnalysis(
            rule="velocity",
            score=settings.weight_velocity,  # 20 points
            triggered=True,
            details={
                "delta_seconds": delta_seconds,
                "threshold_seconds": 10
            }
        )

    return RuleAnalysis(rule="velocity", score=0, triggered=False, ...)
```

**Real-world scenario:**
```
Transaction 1: 10:03:10 - Buy coffee
Transaction 2: 10:03:15 - Buy phone (5 seconds later!)

→ TRIGGERED: Humans can't physically complete two transactions 5 seconds apart
→ Likely automated fraud or compromised credentials
```

**Configuration:**
- `MIN_TXN_GAP_SECONDS`: Threshold in seconds (default: 10)
- `WEIGHT_VELOCITY`: Points added when triggered (default: 20)

---

### Rule 2: Impossible Travel

**File:** `backend/app/services/rules/travel.py`

**Purpose:** Detect when a card is used in two locations that would require impossible travel speed.

**Logic:**
```
1. Calculate distance between current and last transaction location
2. Calculate time between transactions
3. Calculate implied travel speed
IF speed > 800 km/h
THEN add 30 points to risk score
```

**Implementation:**
```python
def check_impossible_travel(
    latest_location: Optional[GeoPoint],
    current_lon: Optional[float],
    current_lat: Optional[float],
    delta_seconds: Optional[float],
) -> RuleAnalysis:

    # Need both locations and time to calculate
    if latest_location is None or current_lon is None or delta_seconds is None:
        return RuleAnalysis(rule="impossible_travel", score=0, triggered=False, ...)

    # Calculate distance using Haversine formula
    distance_km = haversine_km(
        prev_lon, prev_lat,  # Last transaction location
        current_lon, current_lat  # Current transaction location
    )

    # Calculate implied speed
    delta_hours = delta_seconds / 3600
    speed_kmh = distance_km / delta_hours

    # Check against threshold (default: 800 km/h - faster than commercial planes)
    if speed_kmh > settings.impossible_travel_kmh:
        return RuleAnalysis(
            rule="impossible_travel",
            score=settings.weight_impossible_travel,  # 30 points
            triggered=True,
            details={
                "distance_km": distance_km,
                "time_hours": delta_hours,
                "speed_kmh": speed_kmh,
                "threshold_kmh": 800
            }
        )
```

**The Haversine Formula:**

**File:** `backend/app/utils/geo.py`

```python
def haversine_km(lon1, lat1, lon2, lat2) -> float:
    """
    Calculate great-circle distance between two points on Earth.
    Uses the Haversine formula for spherical trigonometry.
    """
    R = 6371.0088  # Earth's radius in km

    # Convert to radians
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])

    # Haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))

    return R * c  # Distance in kilometers
```

**Real-world scenario:**
```
Transaction 1: 09:00 Jakarta, Indonesia (-6.2088, 106.8456)
Transaction 2: 09:30 Surabaya, Indonesia (-7.2575, 112.7521)

Distance: ~780 km
Time: 30 minutes (0.5 hours)
Speed: 780 / 0.5 = 1,560 km/h

→ TRIGGERED: Faster than any commercial aircraft!
→ Card likely cloned and used in two places simultaneously
```

**Why 800 km/h threshold?**
- Commercial jets cruise at ~900 km/h
- Accounting for boarding/security time, 800 km/h is impossible for legitimate travel
- Could be lowered for regions without air travel

---

### Rule 3: Blacklist Proximity

**File:** `backend/app/services/rules/blacklist.py`

**Purpose:** Flag transactions occurring near known fraud hotspots.

**Logic:**
```
IF transaction location is within 500 meters of a blacklist location
THEN add 10-35 points based on blacklist category
```

**Categories and weights:**
| Category | Weight | Description |
|----------|--------|-------------|
| `fraud_hub` | 35 | Known fraud operation centers |
| `scammer` | 25 | Reported scammer locations |
| `wifi` | 15 | Public WiFi with fraud history |
| `merchant` | 10 | Merchants with suspicious activity |

**Implementation:**
```python
async def check_blacklist_proximity(
    db: Database,
    lon: Optional[float],
    lat: Optional[float],
) -> RuleAnalysis:

    if lon is None or lat is None:
        return RuleAnalysis(rule="blacklist_proximity", score=0, triggered=False, ...)

    # MongoDB geospatial query - returns first match within radius
    # No need to calculate exact distance (optimization)
    nearby = db.blacklist_locations.find_one({
        "location": {
            "$nearSphere": {
                "$geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat]
                },
                "$maxDistance": 500  # meters
            }
        }
    })

    if nearby:
        category = nearby["category"]
        weight = settings.blacklist_weights[category]  # 10-35 points

        return RuleAnalysis(
            rule="blacklist_proximity",
            score=weight,
            triggered=True,
            details={
                "category": category,
                "threshold_m": 500
            }
        )
```

**Known Fraud Hotspots (from mock data):**
```python
FRAUD_HOTSPOTS = [
    {"city": "Jakarta", "province": "DKI Jakarta", "coords": [106.8297, -6.1387], "category": "fraud_hub"},   # Mangga Dua
    {"city": "Jakarta", "province": "DKI Jakarta", "coords": [106.8178, -6.1456], "category": "fraud_hub"},   # Glodok
    {"city": "Jakarta", "province": "DKI Jakarta", "coords": [106.8124, -6.1862], "category": "scammer"},     # Tanah Abang
    {"city": "Surabaya", "province": "Jawa Timur", "coords": [112.7374, -7.2621], "category": "wifi"},
    {"city": "Bandung", "province": "Jawa Barat", "coords": [107.6191, -6.9175], "category": "merchant"},
    {"city": "Medan", "province": "Sumatera Utara", "coords": [98.6722, 3.5952], "category": "scammer"},
]
```

---

### Rule 4: Password Frequency

**File:** `backend/app/services/rules/password.py`

**Purpose:** Detect accounts with unusually frequent password changes (potential account takeover).

**Logic:**
```
IF average days between password changes < 7 days
THEN add 15 points to risk score
```

**Implementation:**
```python
def check_password_frequency(
    avg_gap_change_password: Optional[float],
) -> RuleAnalysis:

    # No password data? No issue.
    if avg_gap_change_password is None:
        return RuleAnalysis(rule="password_frequency", score=0, triggered=False, ...)

    # Check against threshold
    if avg_gap_change_password < settings.password_threshold_days:  # 7 days
        return RuleAnalysis(
            rule="password_frequency",
            score=settings.weight_password,  # 15 points
            triggered=True,
            details={
                "avg_gap_days": avg_gap_change_password,
                "threshold_days": 7
            }
        )
```

**Why this matters:**
- Fraudsters who gain access often change passwords repeatedly
- Legitimate users rarely change passwords more than monthly
- Frequent changes suggest ongoing account takeover attempts

---

### Rule 5: Holiday Check

**File:** `backend/app/services/rules/holiday.py`

**Purpose:** Flag transactions during holiday periods (historically higher fraud rates).

**Logic:**
```
IF transaction date falls within a holiday period
THEN add 10 points to risk score
```

**Implementation:**
```python
async def check_holiday(
    db: Database,
    timestamp: datetime,
) -> RuleAnalysis:

    # Normalize to start of day
    txn_date = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)

    # Query for overlapping holiday
    holiday = db.holidays.find_one({
        "date_range.start": {"$lte": txn_date},
        "date_range.end": {"$gte": txn_date}
    })

    if holiday:
        # Single weight for all holidays (simplified)
        return RuleAnalysis(
            rule="holiday",
            score=settings.weight_holiday,  # 10 points
            triggered=True,
            details={
                "holiday_name": holiday["name"]
            }
        )
```

**Indonesian holidays with date ranges:**
```javascript
{
  name: "Idul Fitri",
  date_range: {
    start: ISODate("2025-03-30"),
    end: ISODate("2025-04-04")  // 5-day holiday period
  },
  is_cuti_bersama: true
}
```

**Why holidays matter:**
- Staff shortages at banks during holidays
- Delayed fraud detection
- Customers traveling (easier to miss suspicious activity)
- Fraudsters exploit reduced monitoring

---

## 5. Score Aggregation & Risk Classification

**File:** `backend/app/services/fraud.py`

### How Scores Are Combined

```python
def calculate_final_score(analysis: List[RuleAnalysis]) -> Tuple[int, str]:
    # Sum all triggered rule scores
    total = sum(rule.score for rule in analysis)

    # Cap at 100
    final_score = min(100, total)

    # Determine risk level
    risk_level = calculate_risk_level(final_score)

    return final_score, risk_level
```

### Risk Level Classification

```python
def calculate_risk_level(final_score: int) -> str:
    if final_score >= 70:      # RISK_THRESHOLD_HIGH
        return "high"
    elif final_score >= 40:    # RISK_THRESHOLD_MEDIUM
        return "medium"
    return "low"
```

### Example Score Calculations

**Example 1: Clean Transaction**
```
Velocity:          0 (last txn was 1 hour ago)
Impossible Travel: 0 (same city, normal speed)
Blacklist:         0 (not near any blacklist)
Password:          0 (90-day avg between changes)
Holiday:           0 (regular business day)
─────────────────────
TOTAL:             0 → LOW RISK
```

**Example 2: Suspicious Transaction**
```
Velocity:          0 (last txn was 30 min ago)
Impossible Travel: 0 (same city)
Blacklist:         35 (near fraud hub!)
Password:          15 (avg 5 days between changes!)
Holiday:           0 (regular business day)
─────────────────────
TOTAL:             50 → MEDIUM RISK
```

**Example 3: Highly Suspicious Transaction**
```
Velocity:          20 (3 seconds since last txn!)
Impossible Travel: 30 (900 km/h implied speed!)
Blacklist:         25 (near scammer location)
Password:          15 (avg 4 days between changes)
Holiday:           10 (during Idul Fitri)
─────────────────────
TOTAL:             100 (capped) → HIGH RISK
```

---

## 6. Code Walkthrough

### Architecture: Rules Own Their Logic

**Key Design Principle:** Each rule file owns its complete logic (DB query + evaluation). The orchestrator (`fraud.py`) just calls rules in parallel - no duplicated logic.

```
services/
├── fraud.py              # Orchestrator only (~310 lines)
└── rules/
    ├── velocity.py       # CPU-only rule
    ├── travel.py         # CPU-only rule  
    ├── password.py       # CPU-only rule
    ├── blacklist.py      # Async rule (owns its DB query)
    └── holiday.py        # Async rule (owns its DB query)
```

### Rule Types

**CPU-only rules** (no DB access):
- `check_velocity()` - Compares timestamps
- `check_impossible_travel()` - Haversine distance calculation
- `check_password_frequency()` - Simple threshold check

**Async rules** (own their DB queries):
- `check_blacklist_proximity()` - Queries `blacklist_locations` collection
- `check_holiday()` - Queries `holidays` collection

### The Main Scoring Flow

**File:** `backend/app/services/fraud.py`

```python
async def score_transaction(self, request: ScoreTransactionRequest) -> Tuple[Transaction, TimingBreakdown]:
    timing = TimingBreakdown()
    start_time = time.perf_counter()

    # ═══════════════════════════════════════════════════════════
    # PHASE 1: PARALLEL - Customer fetch + DB-based rules
    # Each rule owns its DB query - no logic duplication!
    # ═══════════════════════════════════════════════════════════
    parallel_read_start = time.perf_counter()
    
    (customer_doc, customer_time), (blacklist_result, blacklist_time), (holiday_result, holiday_time) = (
        await asyncio.gather(
            fetch_customer_async(self.db, request.customer_id),
            check_blacklist_proximity(self.db, request.lon, request.lat),  # Rule owns query
            check_holiday(self.db, request.timestamp),                      # Rule owns query
        )
    )
    
    timing.parallel_reads_ms = (time.perf_counter() - parallel_read_start) * 1000
    
    customer = Customer.from_mongo(customer_doc)
    features = customer.features

    # ═══════════════════════════════════════════════════════════
    # PHASE 2: CPU-only rules (need customer data)
    # ═══════════════════════════════════════════════════════════
    velocity_result = check_velocity(features.latest_time_transaction, request.timestamp)
    travel_result = check_impossible_travel(features.latest_location, request.lon, request.lat, delta_seconds)
    password_result = check_password_frequency(features.avg_gap_change_password)

    # Collect all results
    analysis = [velocity_result, travel_result, blacklist_result, password_result, holiday_result]
    final_score, risk_level = calculate_final_score(analysis)

    # ═══════════════════════════════════════════════════════════
    # PHASE 3: PARALLEL DB WRITES
    # ═══════════════════════════════════════════════════════════
    update_time, (txn_id, insert_time) = await asyncio.gather(
        update_customer_async(self.db, request.customer_id, update_fields),
        insert_transaction_async(self.db, txn_doc),
    )
    
    return transaction, timing
```

### Example: Blacklist Rule (Owns Its DB Query)

**File:** `backend/app/services/rules/blacklist.py`

```python
async def check_blacklist_proximity(
    db: AsyncDatabase,
    lon: Optional[float],
    lat: Optional[float],
) -> Tuple[RuleAnalysis, float]:
    """Rule owns its complete logic: DB query + evaluation."""
    settings = get_settings()
    t0 = time.perf_counter()

    if lon is None or lat is None:
        return RuleAnalysis(rule="blacklist_proximity", score=0, triggered=False, ...), 0.0

    # DB query is part of the rule
    nearby = await db.blacklist_locations.find_one({
        "location": {
            "$nearSphere": {
                "$geometry": {"type": "Point", "coordinates": [lon, lat]},
                "$maxDistance": settings.blacklist_radius_meters,
            }
        }
    })
    
    elapsed_ms = (time.perf_counter() - t0) * 1000

    if nearby:
        weight = settings.blacklist_weights.get(nearby["category"], 10)
        return RuleAnalysis(rule="blacklist_proximity", score=weight, triggered=True, ...), elapsed_ms

    return RuleAnalysis(rule="blacklist_proximity", score=0, triggered=False, ...), elapsed_ms
```

### Timezone Handling

**File:** `backend/app/utils/timing.py`

MongoDB stores timezone-aware datetimes, but API requests often use naive datetimes:

```python
def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize datetime to UTC for consistent comparisons."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
```

This prevents `TypeError: can't subtract offset-naive and offset-aware datetimes` errors.

---

## 7. Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            INCOMING REQUEST                                  │
│  POST /score-transaction                                                    │
│  { customer_id, account_id, amount, lat, lon, timestamp, ... }             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              VALIDATION                                      │
│  • customer_id format (CUST-XXXXXXXXXXXX)                                   │
│  • channel enum (Livin, KOPRA, ATM, QRIS, Branch, Ecom)                    │
│  • device_type enum (ios, android, web)                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DATABASE: FETCH CUSTOMER                             │
│  Collection: customers                                                       │
│  Query: { customer_id: "CUST-7F3A2B1C9E4D" }                                │
│                                                                              │
│  Returns:                                                                    │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ customer_id: "CUST-7F3A2B1C9E4D"                                       │ │
│  │ name: "Budi Santoso"                                                   │ │
│  │ account_ids: ["ACC-7A8B9C0D"]                                          │ │
│  │ features: {                                                             │ │
│  │   latest_time_transaction: 2025-12-10T09:00:00Z  ← Used by velocity    │ │
│  │   latest_location: [106.8, -6.2]                 ← Used by travel      │ │
│  │   avg_gap_change_password: 45.5                  ← Used by password    │ │
│  │ }                                                                       │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           FRAUD RULES ENGINE                                 │
│                                                                              │
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐ │
│  │   VELOCITY CHECK    │  │ IMPOSSIBLE TRAVEL   │  │ BLACKLIST PROXIMITY │ │
│  │                     │  │                     │  │                     │ │
│  │ Input:              │  │ Input:              │  │ Input:              │ │
│  │ • last_txn_time     │  │ • last_location     │  │ • current lat/lon   │ │
│  │ • current_time      │  │ • current_location  │  │                     │ │
│  │                     │  │ • time_delta        │  │ DB Query:           │ │
│  │ Logic:              │  │                     │  │ $nearSphere within  │ │
│  │ delta < 10 sec?     │  │ Logic:              │  │ 500m radius         │ │
│  │                     │  │ speed > 800 km/h?   │  │                     │ │
│  │ Score: 0 or 20      │  │                     │  │ Score: 0 or 10-35   │ │
│  └─────────────────────┘  │ Score: 0 or 30      │  └─────────────────────┘ │
│                           └─────────────────────┘                           │
│                                                                              │
│  ┌─────────────────────┐  ┌─────────────────────┐                          │
│  │ PASSWORD FREQUENCY  │  │   HOLIDAY CHECK     │                          │
│  │                     │  │                     │                          │
│  │ Input:              │  │ Input:              │                          │
│  │ • avg_gap_password  │  │ • transaction_date  │                          │
│  │                     │  │                     │                          │
│  │ Logic:              │  │ DB Query:           │                          │
│  │ avg_gap < 7 days?   │  │ date in range?      │                          │
│  │                     │  │                     │                          │
│  │ Score: 0 or 15      │  │ Score: 0 or 10      │                          │
│  └─────────────────────┘  └─────────────────────┘                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          SCORE AGGREGATION                                   │
│                                                                              │
│  velocity_score + travel_score + blacklist_score + password_score + holiday │
│        20       +      0       +       35        +       0        +    0    │
│                                    =                                         │
│                                   55                                         │
│                                    │                                         │
│                         ┌──────────┴──────────┐                             │
│                         │                     │                              │
│                    [0-39: LOW]    [40-69: MEDIUM]    [70-100: HIGH]         │
│                                        ▲                                     │
│                                        │                                     │
│                              55 = MEDIUM RISK                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    DATABASE: UPDATE CUSTOMER FEATURES                        │
│  Collection: customers                                                       │
│  Update: {                                                                   │
│    "features.latest_time_transaction": <current_timestamp>,                 │
│    "features.latest_location": <current_location>                           │
│  }                                                                           │
│                                                                              │
│  → Now ready for NEXT transaction's velocity/travel checks                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    DATABASE: INSERT TRANSACTION                              │
│  Collection: transactions                                                    │
│  Document includes:                                                          │
│  • All transaction details                                                   │
│  • Complete fraud_score object with analysis breakdown                      │
│  • Shard key fields for distribution                                        │
│  • Device fingerprint details                                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              RESPONSE                                        │
│  {                                                                           │
│    "transaction_id": "675f1a2b3c4d5e6f7a8b9c0d",                           │
│    "risk_score": 55,                                                        │
│    "risk_level": "medium",                                                  │
│    "analysis": [                                                            │
│      { "rule": "velocity", "score": 20, "triggered": true, ... },          │
│      { "rule": "impossible_travel", "score": 0, "triggered": false, ... }, │
│      { "rule": "blacklist_proximity", "score": 35, "triggered": true, ...},│
│      { "rule": "password_frequency", "score": 0, "triggered": false, ... },│
│      { "rule": "holiday", "score": 0, "triggered": false, ... }            │
│    ],                                                                        │
│    "scoring_time_ms": 12.34,                                                │
│    "persistence_time_ms": 8.76,                                             │
│    "total_time_ms": 21.10                                                   │
│  }                                                                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 8. Mock Data Generator

The system includes a comprehensive mock data generator for realistic testing and development.

### Generator Components

| Component | File | Description |
|-----------|------|-------------|
| Indonesian Names | `seed/data/indonesian_names.py` | 8 ethnic groups (Javanese, Sundanese, Batak, Chinese-Indonesian, etc.) with province mapping |
| Provinces/Cities | `seed/data/provinces.py` | 17 Indonesian provinces with actual city coordinates, business districts, shopping centers |
| Device Fingerprints | `seed/data/devices.py` | Indonesian ISP IP ranges (Telkomsel, Indosat, XL), realistic device models (Samsung, Xiaomi, OPPO, Vivo) |
| Customer Profiles | `seed/data/profiles.py` | 8 customer segments with behavioral patterns (mass_market, affluent, student, senior, etc.) |
| Merchants | `seed/data/merchants.py` | 80+ real Indonesian merchants (Tokopedia, Shopee, GoFood, Grab, etc.) across 14 categories |
| Fraud Scenarios | `seed/data/fraud_scenarios.py` | 9 fraud types with injection functions |

### Mock API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /mock/customer` | Generate a realistic mock customer |
| `GET /mock/transaction?fraud_type=velocity` | Generate transaction with optional fraud injection |
| `GET /mock/batch?count=10` | Generate batch of transactions |
| `GET /mock/provinces` | List available provinces |
| `GET /mock/channels` | List transaction channels |
| `GET /mock/fraud-types` | List fraud types for testing |
| `GET /mock/segments` | List customer segments |

### Fraud Types for Testing

| Type | Description | Expected Rules |
|------|-------------|----------------|
| `velocity` | Rapid sequential transactions (1-8 seconds apart) | `["velocity"]` |
| `impossible_travel` | Transaction from far location (>500km) in short time | `["impossible_travel"]` |
| `blacklist` | Transaction near known fraud hotspot | `["blacklist_proximity"]` |
| `ato` | Full account takeover pattern (new device + velocity + large transfer) | `["velocity", "impossible_travel"]` |
| `card_testing` | Small test transactions (1,000-15,000 IDR) before large fraud | `[]` |
| `midnight_burst` | Multiple transactions between midnight and 4am | `[]` |
| `unusual_amount` | Transaction 5-20x normal amount | `[]` |
| `new_device` | First transaction from unknown device | `[]` |
| `geo_anomaly` | Transaction from unexpected region | `["impossible_travel"]` |

### Example: Generate Test Data

```bash
# Generate a customer
curl http://localhost:8000/mock/customer

# Generate a normal transaction
curl http://localhost:8000/mock/transaction

# Generate a fraudulent transaction
curl "http://localhost:8000/mock/transaction?fraud_type=velocity"

# Generate batch with mixed fraud
curl "http://localhost:8000/mock/batch?count=100"
```

---

## 9. Configuration Reference

### All Environment Variables

**File:** `backend/.env`

```bash
# ═══════════════════════════════════════════════════════════════
# DATABASE CONNECTION
# ═══════════════════════════════════════════════════════════════
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>
DB_NAME=RegionalBank_fraud

# ═══════════════════════════════════════════════════════════════
# RULE THRESHOLDS
# These define WHEN a rule triggers
# ═══════════════════════════════════════════════════════════════

# Velocity: Transactions faster than this are suspicious
MIN_TXN_GAP_SECONDS=10           # Default: 10 seconds

# Impossible Travel: Speeds above this are impossible
IMPOSSIBLE_TRAVEL_KMH=800        # Default: 800 km/h

# Blacklist: Transactions within this radius are flagged
BLACKLIST_RADIUS_METERS=500      # Default: 500 meters

# Password: More frequent changes than this are suspicious
PASSWORD_THRESHOLD_DAYS=7        # Default: 7 days

# ═══════════════════════════════════════════════════════════════
# RULE WEIGHTS
# These define HOW MANY POINTS are added when a rule triggers
# ═══════════════════════════════════════════════════════════════

WEIGHT_VELOCITY=20               # Points for rapid transactions
WEIGHT_IMPOSSIBLE_TRAVEL=30      # Points for impossible speed
WEIGHT_PASSWORD=15               # Points for frequent password changes
WEIGHT_HOLIDAY=10                # Points for holiday periods (single weight)

# Blacklist weights by category
WEIGHT_BLACKLIST_FRAUD_HUB=35    # Known fraud centers
WEIGHT_BLACKLIST_SCAMMER=25      # Reported scammer locations
WEIGHT_BLACKLIST_WIFI=15         # Suspicious public WiFi
WEIGHT_BLACKLIST_MERCHANT=10     # Suspicious merchants

# ═══════════════════════════════════════════════════════════════
# RISK CLASSIFICATION
# These define the score boundaries for risk levels
# ═══════════════════════════════════════════════════════════════

RISK_THRESHOLD_MEDIUM=40         # Score >= 40 = Medium risk
RISK_THRESHOLD_HIGH=70           # Score >= 70 = High risk
                                 # Score < 40 = Low risk (implicit)
```

### How Configuration Flows Through the Code

```
.env file
    │
    ▼
pydantic Settings class (backend/app/config.py)
    │
    ▼
@lru_cache() decorator caches settings
    │
    ▼
get_settings() returns cached Settings instance
    │
    ▼
Rules access settings.weight_velocity, settings.min_txn_gap_seconds, etc.
```

**File:** `backend/app/config.py`
```python
class Settings(BaseSettings):
    # These become attributes like settings.weight_velocity
    weight_velocity: int = 20
    weight_impossible_travel: int = 30
    weight_holiday: int = 10  # Single weight for all holidays
    # ... etc

    class Config:
        env_file = ".env"  # Automatically loads from .env file

@lru_cache()  # Only parse env vars once
def get_settings() -> Settings:
    return Settings()
```

---

## 10. Performance Analysis

### Parallel Execution with PyMongo Async

The scoring service uses **parallel execution** to minimize latency. Independent database operations run concurrently using PyMongo's native Async API.

**Execution Flow:**

```
Sequential (old):
┌──────────┬──────────┬──────────┬──────────┬──────────┐
│ Customer │ Blacklist│ Holiday  │ Update   │ Insert   │  = ~750ms
│  150ms   │  150ms   │  150ms   │  150ms   │  150ms   │
└──────────┴──────────┴──────────┴──────────┴──────────┘

Parallel (current):
┌──────────┐ ┌──────────┐
│ Customer │ │ Update   │
│ Blacklist├─┤ Insert   │  = ~300ms (2.5x faster!)
│ Holiday  │ │          │
└──────────┘ └──────────┘
   ~150ms      ~150ms
```

**Code Pattern:**

```python
# PHASE 1: Parallel DB Reads
customer_doc, blacklist_doc, holiday_doc = await asyncio.gather(
    fetch_customer_async(db, customer_id),
    query_blacklist_async(db, lon, lat, radius),
    query_holiday_async(db, txn_date),
)

# PHASE 2: Rule Evaluation (CPU - fast)
# ... evaluate all rules ...

# PHASE 3: Parallel DB Writes
await asyncio.gather(
    update_customer_async(db, customer_id, update_fields),
    insert_transaction_async(db, txn_doc),
)
```

### Time Budget Breakdown

**In Production (same region as Atlas):**

| Operation | Budget | Type | Notes |
|-----------|--------|------|-------|
| Fetch customer | <5ms | DB Read | Single document by indexed field |
| Velocity check | <1ms | CPU | Pure Python comparison |
| Impossible travel | <1ms | CPU | Haversine + comparison |
| Blacklist check | <5ms | DB Read | 2dsphere geo query (no distance calc) |
| Password check | <1ms | CPU | Pure Python comparison |
| Holiday check | <2ms | DB Read | Date range query |
| Score calculation | <1ms | CPU | Sum and compare |
| Update customer | <5ms | DB Write | Single document update |
| Insert transaction | <5ms | DB Write | Single document insert |
| **Parallel Reads** | **<5ms** | | Max of 3 reads (parallel) |
| **Rules** | **<1ms** | | CPU-bound, fast |
| **Parallel Writes** | **<5ms** | | Max of 2 writes (parallel) |
| **Grand Total** | **<15ms** | | Well under 50ms budget |

**From Remote Location (e.g., local dev to Atlas):**

| Phase | Individual Sum | Parallel Wall-Clock |
|-------|----------------|---------------------|
| DB Reads | ~450ms | ~150ms |
| Rules (CPU) | <1ms | <1ms |
| DB Writes | ~300ms | ~150ms |
| **Total** | ~751ms | **~300ms** |

### Detailed Timing Response

The API returns comprehensive timing breakdown:

```json
{
  "timing": {
    "db_customer_fetch_ms": 135.28,
    "db_blacklist_query_ms": 135.30,
    "db_holiday_query_ms": 139.46,
    "db_customer_update_ms": 142.87,
    "db_transaction_insert_ms": 142.58,
    "rule_velocity_ms": 0.01,
    "rule_travel_ms": 0.01,
    "rule_blacklist_ms": 0.01,
    "rule_password_ms": 0.00,
    "rule_holiday_ms": 0.01,
    "total_db_read_ms": 410.04,
    "total_db_write_ms": 285.44,
    "total_rules_ms": 0.05,
    "scoring_ms": 141.87,
    "persistence_ms": 143.62,
    "total_ms": 285.56
  }
}
```

### Why It's Fast

1. **Parallel Execution**
   - Independent DB operations run concurrently
   - PyMongo Async API (no thread pool overhead)
   - ~2.5x speedup vs sequential

2. **Embedded Features**
   - No joins between collections
   - Single read gets everything needed

3. **Indexed Queries**
   - `customer_id` is indexed (shard key)
   - `location` has 2dsphere index
   - `date_range` fields are indexed

4. **Single Shard Targeting**
   - All queries include `customer_id`
   - MongoDB routes directly to correct shard
   - No scatter-gather across shards

5. **Minimal Data Transfer**
   - Only fetch needed fields
   - Customer document is <1KB
   - Blacklist/holiday documents are tiny

6. **Optimized Blacklist Check**
   - Uses `$nearSphere` with `$maxDistance`
   - MongoDB returns first match within radius
   - No need to calculate exact distance in Python

### What Could Make It Slow

| Anti-pattern | Why It's Bad | Our Solution |
|--------------|--------------|--------------|
| Sequential DB calls | Network latency compounds | Parallel with `asyncio.gather()` |
| Thread-based async | Thread pool overhead | Native PyMongo Async API |
| `$lookup` joins | Multiple round trips | Embedded features |
| Scatter queries | Query all shards | Shard key in all queries |
| Large documents | Network transfer | Keep documents small |
| Missing indexes | Collection scans | All queries use indexes |
| Aggregation pipelines | Complex processing | Simple find operations |
| Distance calculations | CPU overhead | Let MongoDB handle it |

---

## Summary

The fraud scoring system is designed for:

1. **Speed**: <50ms end-to-end through careful query design
2. **Accuracy**: 5 complementary rules catch different fraud patterns
3. **Transparency**: Every rule's contribution is visible in the response
4. **Configurability**: All thresholds and weights are environment variables
5. **Scalability**: Sharding design ensures linear scale-out
6. **Testability**: Comprehensive mock data generator with fraud injection

The key insights are:
- **Embedded features** eliminate the need for joins
- **Separated timing metrics** allow monitoring scoring vs persistence independently
- **Realistic mock data** enables thorough testing of all fraud scenarios
- **MongoDB transactions available** for ACID-compliant writes when needed (see `fraud.py`)

---

## Appendix: ACID-Compliant Writes (Optional)

For use cases requiring atomic writes (both customer update and transaction insert succeed or both fail), we've implemented MongoDB multi-document transactions. The code is preserved in `fraud.py` but commented out by default for performance.

### Performance Comparison

| Write Mode | Latency | Atomicity |
|------------|---------|-----------|
| Parallel (default) | ~155ms | ❌ |
| Transaction (ACID) | ~297ms | ✅ |

### To Enable Transactions

In `backend/app/services/fraud.py`, comment out the parallel writes section and uncomment the transaction block:

```python
# Comment out:
# update_time, (txn_id, insert_time) = await asyncio.gather(...)

# Uncomment:
async with self.db.client.start_session() as session:
    await session.start_transaction()
    # ... writes with session=session ...
    await session.commit_transaction()
```

### When to Use

- **Parallel (default)**: Best for high-throughput, real-time scoring where occasional inconsistency is acceptable
- **Transaction**: Use when regulatory requirements mandate atomic audit trails
