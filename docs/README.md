# Documentation

This folder contains detailed technical documentation for the RegionalBank Fraud Detection POC.

## Documents

### Core Documentation

| Document | Description |
|----------|-------------|
| [SCORING-SYSTEM-DEEP-DIVE.md](./SCORING-SYSTEM-DEEP-DIVE.md) | **Start here!** Complete explanation of how the fraud scoring works, step by step, with code walkthroughs and diagrams |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Database schema design, sharding strategy, and architectural decisions |
| [INFRASTRUCTURE.md](./INFRASTRUCTURE.md) | **AWS Deployment** - Terraform infrastructure, ALB, EC2 Auto Scaling, PrivateLink setup |
| [LOAD-TESTING.md](./LOAD-TESTING.md) | **Load Testing** - Built-in load testing system, API endpoints, UI features, performance testing |

### Infrastructure Setup Guides

| Document | Description |
|----------|-------------|
| [EC2-DOCKER-SETUP.md](./EC2-DOCKER-SETUP.md) | EC2 instances with Docker deployment, VPC fundamentals, IAM roles |
| [ALB-SETUP.md](./ALB-SETUP.md) | Application Load Balancer with target groups, health checks, listeners |
| [PRIVATELINK-SETUP.md](./PRIVATELINK-SETUP.md) | MongoDB Atlas PrivateLink with Route 53 DNS configuration |
| [LOCUST-SETUP.md](./LOCUST-SETUP.md) | Distributed Locust load testing from bastion host |
| DEPLOYMENT-RUNBOOK.md | **Quick Reference** - Common commands, resource IDs, deployment steps |

## Quick Navigation

### Understanding the Scoring System

→ Read [SCORING-SYSTEM-DEEP-DIVE.md](./SCORING-SYSTEM-DEEP-DIVE.md)

Covers:
- Complete request flow from API to response
- All 5 fraud rules explained in detail
- Code walkthroughs with actual implementation
- Data flow diagrams
- **Parallel execution architecture**
- **Detailed timing breakdown**
- Performance analysis
- Configuration reference

### Understanding the Database Design

→ Read [ARCHITECTURE.md](./ARCHITECTURE.md)

Covers:
- Why embedded features instead of joins
- Why random customer IDs for even shard distribution
- Shard key design for transactions
- Index strategy
- Collection schemas
- **PyMongo Async API for parallel execution**
- **Timing metrics separation**

### AWS Production Deployment

→ Read [INFRASTRUCTURE.md](./INFRASTRUCTURE.md)

Covers:
- **Terraform infrastructure as code**
- VPC with public/private subnets (2 AZs)
- Application Load Balancer (replaces nginx)
- EC2 Auto Scaling Group (c6i.2xlarge)
- MongoDB Atlas PrivateLink setup
- CloudWatch monitoring and logs
- Cost estimation and optimization
- Complete teardown with verification

### Load Testing

→ Read [LOAD-TESTING.md](./LOAD-TESTING.md)

Covers:
- **Built-in load testing triggered from UI**
- How the HTTP-based load generator works
- API endpoints for programmatic testing
- Local vs production testing architecture
- Performance expectations and troubleshooting

## Key Concepts Summary

### The Five Fraud Rules

| Rule | Points | Detects |
|------|--------|---------|
| Velocity | 20 | Transactions <10 seconds apart |
| Impossible Travel | 30 | Location changes >800 km/h |
| Blacklist Proximity | 10-35 | Transaction within 500m of fraud hotspot |
| Password Frequency | 15 | Password changes <7 days apart average |
| Holiday | 5-10 | Transaction during holiday periods |

### Risk Levels

| Score Range | Level | Action |
|-------------|-------|--------|
| 0-39 | Low | Approve automatically |
| 40-69 | Medium | Additional verification recommended |
| 70-100 | High | Block or manual review |

### Performance Target

- **Total scoring time:** <50ms (local) / ~300ms (remote to Atlas)
- **Database operations:** 5 (3 reads, 2 writes) - **executed in parallel**
- **Query routing:** Single shard targeted (no scatter-gather)
- **Parallel speedup:** ~2.5x vs sequential execution

## Performance Optimization (Session: Dec 2025)

### Architecture: Clean Separation of Concerns

Each rule owns its complete logic (DB query + evaluation). The orchestrator just calls rules in parallel.

```
services/
├── fraud.py              # Orchestrator (~310 lines)
└── rules/
    ├── velocity.py       # CPU-only (no DB)
    ├── travel.py         # CPU-only (no DB)
    ├── password.py       # CPU-only (no DB)
    ├── blacklist.py      # Async (owns DB query)
    └── holiday.py        # Async (owns DB query)
```

### Parallel Execution with PyMongo Async

```
PHASE 1: Parallel (~145ms wall-clock)
├── fetch_customer_async()
├── check_blacklist_proximity()  ← rule owns its DB query
└── check_holiday()              ← rule owns its DB query

PHASE 2: CPU Rules (<1ms)
├── check_velocity()
├── check_impossible_travel()
└── check_password_frequency()

PHASE 3: Parallel Writes (~190ms wall-clock)
├── update_customer_async()
└── insert_transaction_async()

TOTAL: ~335ms (3x faster than sequential!)
```

### Why PyMongo Async over Motor?

| Aspect | Motor | PyMongo Async |
|--------|-------|---------------|
| Status | **Deprecated** (EOL 2027) | Active, native |
| Architecture | Thread pool | Native asyncio |
| Performance | Good | Better (no thread overhead) |

### Timing Breakdown

The API returns detailed timing metrics:

```json
{
  "timing": {
    "db_customer_fetch_ms": 143.99,
    "db_blacklist_query_ms": 143.35,
    "db_holiday_query_ms": 142.92,
    "db_customer_update_ms": 146.96,
    "db_transaction_insert_ms": 190.48,
    "rule_velocity_ms": 0.04,
    "rule_travel_ms": 0.03,
    "rule_password_ms": 0.01,
    "parallel_reads_ms": 144,
    "parallel_writes_ms": 191,
    "total_ms": 336
  }
}
```

**Note:** `rule_blacklist_ms` and `rule_holiday_ms` are ~0 because these rules' DB query time is already captured in `db_blacklist_query_ms` and `db_holiday_query_ms`. The CPU evaluation is negligible.

### ACID-Compliant Transactions (Optional)

MongoDB multi-document transactions are implemented but disabled by default for performance. Enable them when atomicity is critical.

| Write Mode | Latency | Atomicity | Use Case |
|------------|---------|-----------|----------|
| **Parallel** (default) | ~155ms | ❌ | Real-time scoring, high throughput |
| **Transaction** | ~297ms | ✅ ACID | Regulatory compliance, audit trails |

To enable: uncomment the transaction block in `backend/app/services/fraud.py`.

```python
# PyMongo Async Transaction Pattern
async with self.db.client.start_session() as session:
    await session.start_transaction()  # Coroutine, not context manager!
    try:
        await db.customers.update_one(..., session=session)
        await db.transactions.insert_one(..., session=session)
        await session.commit_transaction()
    except:
        await session.abort_transaction()
        raise
```
