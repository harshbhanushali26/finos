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