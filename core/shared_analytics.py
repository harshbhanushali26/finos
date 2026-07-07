"""
core/shared_analytics.py

Shared read-only aggregate queries over Transaction, used by:
- tools/analytics.py
- tools/budget.py
- agent/insights.py
- api/routes/analytics.py
- api/routes/budget.py

Each caller keeps its own response formatting and month/date-range
resolution policy. This file only owns the raw aggregate queries that
were previously duplicated.
"""

from datetime import date as dt_date
from sqlmodel import select, func

from core.models import Transaction


def sum_by_type(db, user_id: int, type_: str, start: dt_date, end: dt_date) -> float:
    """Sum transaction amounts for a user/type within an inclusive date range."""
    result = db.exec(
        select(func.sum(Transaction.amount)).where(
            Transaction.user_id == user_id,
            Transaction.type == type_,
            Transaction.date >= start,
            Transaction.date <= end,
        )
    ).one()
    return float(result or 0)


def category_breakdown(db, user_id: int, type_: str, start: dt_date, end: dt_date) -> dict[str, float]:
    """Return {category: total} for a user/type within an inclusive date range."""
    rows = db.exec(
        select(Transaction.category, func.sum(Transaction.amount))
        .where(
            Transaction.user_id == user_id,
            Transaction.type == type_,
            Transaction.date >= start,
            Transaction.date <= end,
        )
        .group_by(Transaction.category)
    ).all()
    return {cat: float(total) for cat, total in rows}