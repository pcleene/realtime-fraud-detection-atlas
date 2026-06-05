# Holiday seed data generator

from datetime import datetime
from typing import Dict, List


# Indonesian national holidays 2025 with date ranges
HOLIDAYS_2025 = [
    {"name": "Tahun Baru", "description": "New Year's Day", "start": "2025-01-01", "end": "2025-01-01", "is_cuti_bersama": False},
    {"name": "Imlek", "description": "Chinese New Year", "start": "2025-01-29", "end": "2025-01-29", "is_cuti_bersama": False},
    {"name": "Isra Mi'raj", "description": "The Night Journey of Prophet Muhammad", "start": "2025-02-27", "end": "2025-02-27", "is_cuti_bersama": False},
    {"name": "Nyepi", "description": "Balinese Day of Silence", "start": "2025-03-29", "end": "2025-03-29", "is_cuti_bersama": False},
    {"name": "Idul Fitri", "description": "Lebaran holiday period", "start": "2025-03-30", "end": "2025-04-04", "is_cuti_bersama": True},
    {"name": "Wafat Isa Al-Masih", "description": "Good Friday", "start": "2025-04-18", "end": "2025-04-18", "is_cuti_bersama": False},
    {"name": "Hari Buruh", "description": "International Labour Day", "start": "2025-05-01", "end": "2025-05-01", "is_cuti_bersama": False},
    {"name": "Waisak", "description": "Buddha's Birthday", "start": "2025-05-12", "end": "2025-05-12", "is_cuti_bersama": False},
    {"name": "Kenaikan Isa Al-Masih", "description": "Ascension of Jesus Christ", "start": "2025-05-29", "end": "2025-05-29", "is_cuti_bersama": False},
    {"name": "Pancasila", "description": "Pancasila Day", "start": "2025-06-01", "end": "2025-06-01", "is_cuti_bersama": False},
    {"name": "Idul Adha", "description": "Feast of the Sacrifice", "start": "2025-06-06", "end": "2025-06-07", "is_cuti_bersama": True},
    {"name": "Tahun Baru Islam", "description": "Islamic New Year", "start": "2025-06-27", "end": "2025-06-27", "is_cuti_bersama": False},
    {"name": "Kemerdekaan", "description": "Indonesian Independence Day", "start": "2025-08-17", "end": "2025-08-17", "is_cuti_bersama": False},
    {"name": "Maulid Nabi", "description": "Prophet Muhammad's Birthday", "start": "2025-09-05", "end": "2025-09-05", "is_cuti_bersama": False},
    {"name": "Natal", "description": "Christmas holiday period", "start": "2025-12-25", "end": "2025-12-26", "is_cuti_bersama": True},
]

# Also add 2024 holidays for historical transactions
HOLIDAYS_2024 = [
    {"name": "Tahun Baru", "description": "New Year's Day", "start": "2024-01-01", "end": "2024-01-01", "is_cuti_bersama": False},
    {"name": "Imlek", "description": "Chinese New Year", "start": "2024-02-10", "end": "2024-02-10", "is_cuti_bersama": False},
    {"name": "Isra Mi'raj", "description": "The Night Journey of Prophet Muhammad", "start": "2024-02-08", "end": "2024-02-08", "is_cuti_bersama": False},
    {"name": "Nyepi", "description": "Balinese Day of Silence", "start": "2024-03-11", "end": "2024-03-11", "is_cuti_bersama": False},
    {"name": "Idul Fitri", "description": "Lebaran holiday period", "start": "2024-04-10", "end": "2024-04-15", "is_cuti_bersama": True},
    {"name": "Wafat Isa Al-Masih", "description": "Good Friday", "start": "2024-03-29", "end": "2024-03-29", "is_cuti_bersama": False},
    {"name": "Hari Buruh", "description": "International Labour Day", "start": "2024-05-01", "end": "2024-05-01", "is_cuti_bersama": False},
    {"name": "Waisak", "description": "Buddha's Birthday", "start": "2024-05-23", "end": "2024-05-23", "is_cuti_bersama": False},
    {"name": "Kenaikan Isa Al-Masih", "description": "Ascension of Jesus Christ", "start": "2024-05-09", "end": "2024-05-09", "is_cuti_bersama": False},
    {"name": "Pancasila", "description": "Pancasila Day", "start": "2024-06-01", "end": "2024-06-01", "is_cuti_bersama": False},
    {"name": "Idul Adha", "description": "Feast of the Sacrifice", "start": "2024-06-17", "end": "2024-06-18", "is_cuti_bersama": True},
    {"name": "Tahun Baru Islam", "description": "Islamic New Year", "start": "2024-07-07", "end": "2024-07-07", "is_cuti_bersama": False},
    {"name": "Kemerdekaan", "description": "Indonesian Independence Day", "start": "2024-08-17", "end": "2024-08-17", "is_cuti_bersama": False},
    {"name": "Maulid Nabi", "description": "Prophet Muhammad's Birthday", "start": "2024-09-16", "end": "2024-09-16", "is_cuti_bersama": False},
    {"name": "Natal", "description": "Christmas holiday period", "start": "2024-12-25", "end": "2024-12-26", "is_cuti_bersama": True},
]


def parse_date(date_str: str) -> datetime:
    """Parse date string to datetime."""
    return datetime.strptime(date_str, "%Y-%m-%d")


def generate_holiday_document(holiday_data: Dict, year: int) -> Dict:
    """
    Generate a single holiday document.

    Args:
        holiday_data: Holiday data dict with name, start, end, etc.
        year: Year for the holiday

    Returns:
        Holiday document dict ready for MongoDB insertion.
    """
    return {
        "name": holiday_data["name"],
        "description": holiday_data["description"],
        "date_range": {
            "start": parse_date(holiday_data["start"]),
            "end": parse_date(holiday_data["end"]),
        },
        "is_cuti_bersama": holiday_data["is_cuti_bersama"],
        "year": year,
    }


def generate_holidays() -> List[Dict]:
    """
    Generate all holiday documents for 2024 and 2025.

    Returns:
        List of holiday documents
    """
    holidays = []

    for holiday in HOLIDAYS_2024:
        holidays.append(generate_holiday_document(holiday, 2024))

    for holiday in HOLIDAYS_2025:
        holidays.append(generate_holiday_document(holiday, 2025))

    return holidays
