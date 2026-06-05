"""
Behavioral rules: var_9, var_11, var_22.

Customer behavior patterns and beneficiary checks.
"""

from datetime import datetime
from typing import Dict, List, Optional

from app.models.transaction import RuleResult
from app.models.customer import LoanIncoming


def check_var_9(at3: float, z1: datetime, pot_i_recent: List[LoanIncoming],
                loan_window_hours: int, outflow_ratio: float, weight: int) -> RuleResult:
    """Online loan money-out pattern. Received loan -> rapid outflow."""
    if not pot_i_recent:
        return RuleResult(rule="var_9", triggered=False, weight=weight, score=0,
                          details={"recent_loans": 0})

    z1_n = z1.replace(tzinfo=None) if z1.tzinfo else z1

    for loan in pot_i_recent:
        loan_z1 = loan.z1.replace(tzinfo=None) if loan.z1.tzinfo else loan.z1
        hours_since = (z1_n - loan_z1).total_seconds() / 3600
        if 0 <= hours_since < loan_window_hours:
            if loan.at3 > 0 and at3 > outflow_ratio * loan.at3:
                return RuleResult(
                    rule="var_9", triggered=True, weight=weight, score=weight,
                    details={
                        "loan_amount": loan.at3,
                        "outflow_amount": at3,
                        "ratio": round(at3 / loan.at3, 4),
                        "hours_since_loan": round(hours_since, 2),
                        "provider": loan.q2,
                    },
                )

    return RuleResult(rule="var_9", triggered=False, weight=weight, score=0,
                      details={"recent_loans": len(pot_i_recent)})


def check_var_11(service: int, service_ever: List[int], weight: int) -> RuleResult:
    """First-time service usage."""
    triggered = service not in service_ever
    return RuleResult(
        rule="var_11", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"service": service, "first_time": triggered,
                 "services_used": len(service_ever)},
    )


def check_var_22(b2: str, b24_list: List[str], b24_count: int,
                 embed_limit: int, weight: int) -> RuleResult:
    """Unknown beneficiary -- not in customer's known beneficiary list.

    If b24_count <= embed_limit, check b24_list directly.
    If b24_count > embed_limit AND b2 not in b24_list, set needs_overflow_check=True
    for the scoring service to check pot_nb_overflow (rare 4th DB op).
    """
    if b2 in b24_list:
        return RuleResult(rule="var_22", triggered=False, weight=weight, score=0,
                          details={"b2": b2, "known": True})

    if b24_count > embed_limit:
        # Need overflow check -- scoring service handles the DB lookup
        return RuleResult(
            rule="var_22", triggered=False, weight=weight, score=0,
            needs_overflow_check=True,
            details={"b2": b2, "b24_count": b24_count, "needs_overflow": True},
        )

    # Not in list and count is within limit -- truly unknown
    return RuleResult(
        rule="var_22", triggered=True, weight=weight,
        score=weight,
        details={"b2": b2, "known": False, "b24_count": b24_count},
    )
