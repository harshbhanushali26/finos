"""Shared backend utilities — date math used across API routes.

Kept separate from agent/utils.py (which stays unchanged from finance-agent)
to avoid the API layer importing from the agent layer.
"""

from calendar import monthrange
from datetime import date as dt_date


def current_month_range() -> tuple[dt_date, dt_date]:
    """Return (start, end) dates for the current calendar month."""
    today = dt_date.today()
    last = monthrange(today.year, today.month)[1]
    return dt_date(today.year, today.month, 1), dt_date(today.year, today.month, last)


def get_last_n_months(n: int) -> list[str]:
    """Return the n calendar months prior to the current month, oldest first, as 'YYYY-MM' strings."""
    today = dt_date.today()
    months = []
    y, m = today.year, today.month
    for _ in range(n):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        months.append(f"{y:04d}-{m:02d}")
    return list(reversed(months))


def month_range(month: str) -> tuple[dt_date, dt_date]:
    """Return (first_day, last_day) date objects for a 'YYYY-MM' string.
    Consolidates the identical function previously duplicated in
    tools/analytics.py, tools/budget.py, and agent/insights.py."""
    year, mon = map(int, month.split("-"))
    last_day = monthrange(year, mon)[1]
    return dt_date(year, mon, 1), dt_date(year, mon, last_day)