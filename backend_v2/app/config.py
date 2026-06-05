"""
V2 Configuration — All 31 rule weights + thresholds as environment variables.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # MongoDB
    mongodb_uri: str = "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"
    db_name: str = "RegionalBank_fraud_prod"

    # Weights (31 rules)
    weight_var_1: int = 15    # destination account blacklist
    weight_var_2: int = 15    # fraud cascade 24h
    weight_var_3: int = 10    # email blacklist
    weight_var_4: int = 5     # risky device type
    weight_var_5: int = 10    # suspicious merchant name
    weight_var_6: int = 10    # gambling affiliation
    weight_var_7: int = 10    # phone blacklist
    weight_var_8: int = 8     # velocity (seconds)
    weight_var_9: int = 10    # loan money-out pattern
    weight_var_10: int = 5    # velocity (days)
    weight_var_11: int = 3    # first-time service
    weight_var_12: int = 5    # amount vs service limit
    weight_var_13: int = 5    # unusual transaction time
    weight_var_14: int = 5    # amount vs historical avg
    weight_var_15: int = 8    # amount to balance ratio
    weight_var_16: int = 5    # repetitive amount pattern
    weight_var_17: int = 5    # amount spike
    weight_var_18: int = 8    # cumulative amount vs balance
    weight_var_19: int = 8    # post-provisioning cumulative
    weight_var_20: int = 5    # exact amount repetition
    weight_var_21: int = 3    # amount drop
    weight_var_22: int = 5    # unknown beneficiary
    weight_var_23: int = 10   # compliance watchlist
    weight_var_24: int = 8    # post-card-change
    weight_var_25: int = 5    # high-risk device
    weight_var_26: int = 8    # post-provisioning
    weight_var_28: int = 5    # amount volatility
    weight_var_29: int = 5    # cumulative sum
    weight_var_30: int = 3    # repetitive purpose
    weight_var_31: int = 3    # purpose to amount ratio

    # Thresholds
    min_txn_gap_seconds: int = 10          # var_8
    min_txn_gap_days: int = 0              # var_10
    amount_to_limit_ratio: float = 0.80    # var_12
    amount_to_balance_ratio: float = 0.50  # var_15
    amount_spike_ratio: float = 5.0        # var_17
    amount_drop_ratio: float = 0.10        # var_21
    exact_repeat_count: int = 3            # var_20
    repetitive_window_size: int = 10       # var_16, var_20, var_30
    post_card_change_hours: int = 24       # var_24
    post_provisioning_hours: int = 24      # var_26
    fraud_cascade_hours: int = 24          # var_2
    loan_moneyout_hours: int = 24          # var_9
    cumulative_window_hours: int = 24      # var_18
    post_prov_cumulative_hours: int = 48   # var_19
    volatility_window_hours: int = 24      # var_28
    cumsum_window_hours: int = 24          # var_29
    loan_outflow_ratio: float = 0.70       # var_9
    purpose_amount_ratio_threshold: float = 0.01  # var_31

    # Risk levels (same as V1)
    risk_threshold_medium: int = 40
    risk_threshold_high: int = 70

    # Array limits
    beneficiary_embed_limit: int = 500
    recent_amounts_limit: int = 10
    recent_purposes_limit: int = 10
    recent_loan_incoming_limit: int = 5

    # Seeding
    seed_customers: int = 10_000
    seed_transactions: int = 50_000
    seed_batch_size: int = 10_000
    seed_workers: int = 8
    seed_warm_to_now_pct: float = 0.05

    # Seeding — chunked pagination
    seed_chunk_size: int = 200_000
    seed_txn_batch_size: int = 10_000
    seed_customer_update_batch: int = 5_000
    seed_time_range_days: int = 30
    seed_max_txns_per_customer: int = 100
    seed_compute_fraud_scores: bool = True

    # Mode toggles
    UPDATE_MODE: str = "standard"   # "standard", "pipeline", or "aggregation" (server-side at6 via $stdDevPop)
    LOOKUP_MODE: str = "memory"     # "memory" (in-memory cache, 3 ops) or "db" (txn_lookups, 4 ops)

    # Application
    log_level: str = "INFO"
    environment: str = "development"

    # Locust
    locust_host: str = "localhost"
    locust_port: int = 8089
    locust_bastion_host: str = "203.0.113.10"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
