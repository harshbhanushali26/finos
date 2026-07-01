"""Shared utility functions for FinOS agent layer.

Pure data/date helpers only — no bridge, no file I/O, no LLM calls.

Functions:
    get_last_n_months — return last N month strings in YYYY-MM format
"""

from datetime import date, timedelta


def get_last_n_months(n: int = 3) -> list[str]:
    """Return last N month strings in YYYY-MM format, most recent first.

    Does not include the current month.

    Args:
        n: Number of past months to return (default 3)

    Returns:
        List of strings like ['2026-05', '2026-04', '2026-03']
    """
    months = []
    first_of_current = date.today().replace(day=1)
    for i in range(1, n + 1):
        d = first_of_current
        for _ in range(i):
            d = (d - timedelta(days=1)).replace(day=1)
        months.append(d.strftime("%Y-%m"))
    return months