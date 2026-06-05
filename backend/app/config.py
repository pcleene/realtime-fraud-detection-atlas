from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Dict


class Settings(BaseSettings):
    # MongoDB
    mongodb_uri: str = "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"
    db_name: str = "RegionalBank_fraud"

    # Thresholds
    blacklist_radius_meters: int = 500
    impossible_travel_kmh: int = 800
    min_txn_gap_seconds: int = 10
    password_threshold_days: int = 7

    # Weights
    weight_velocity: int = 20
    weight_impossible_travel: int = 30
    weight_password: int = 15
    weight_holiday: int = 10  # Single weight for all holidays
    weight_blacklist_fraud_hub: int = 35
    weight_blacklist_scammer: int = 25
    weight_blacklist_wifi: int = 15
    weight_blacklist_merchant: int = 10

    # Risk thresholds
    risk_threshold_medium: int = 40
    risk_threshold_high: int = 70

    # Seeding
    seed_customers: int = 50_000_000
    seed_transactions: int = 100_000_000
    seed_batch_size: int = 10_000
    seed_blacklist: int = 100
    seed_holidays: int = 25
    seed_workers: int = 8

    # Quick test seed (schema validation)
    seed_test_customers: int = 5
    seed_test_transactions: int = 20
    seed_test_blacklist: int = 3

    # Percentage of customers to warm to "now" for immediate fraud testing
    seed_warm_to_now_pct: float = 0.05

    # Application
    log_level: str = "INFO"
    environment: str = "development"

    # Locust load testing proxy
    locust_host: str = "localhost"
    locust_port: int = 8089
    locust_bastion_host: str = "203.0.113.10"  # AWS bastion with Locust

    @property
    def blacklist_weights(self) -> Dict[str, int]:
        return {
            "fraud_hub": self.weight_blacklist_fraud_hub,
            "scammer": self.weight_blacklist_scammer,
            "wifi": self.weight_blacklist_wifi,
            "merchant": self.weight_blacklist_merchant,
        }

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
