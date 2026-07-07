"""
core/shared_budget.py

Shared low-level DB operations for Budget, used by:
- api/routes/budget.py
- tools/budget.py
"""

from sqlmodel import select
from core.models import Budget


def get_user_budgets(db, user_id: int) -> list[Budget]:
    """Return all Budget rows for this user."""
    return db.exec(select(Budget).where(Budget.user_id == user_id)).all()


def get_budget_for_category(db, user_id: int, category: str) -> Budget | None:
    """Fetch the Budget row for a specific category, if one exists."""
    return db.exec(
        select(Budget).where(
            Budget.user_id == user_id,
            Budget.category == category,
        )
    ).first()