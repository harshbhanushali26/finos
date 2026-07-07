"""
FinOS — budget routes (api/routes/budget.py)

GET  /budget/           — all budgets for current user
POST /budget/           — set budget for a category (upsert)
GET  /budget/status     — usage vs limits for current month
GET  /budget/overspend  — categories exceeding their budget this month
"""

from calendar import monthrange
from datetime import date as dt_date
from typing import Optional

from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from api.deps import get_current_user, get_db
from api.schemas import BudgetSet, BudgetStatusItem
from core.models import Budget, User
from core.utils import current_month_range
from core.shared_analytics import category_breakdown
from core.shared_budget import get_user_budgets, get_budget_for_category

router = APIRouter(prefix="/budget", tags=["budget"])


@router.get("/", response_model=list[BudgetSet])
def list_budgets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    budgets = get_user_budgets(db, current_user.id)
    return [BudgetSet(category=b.category, monthly_limit=b.monthly_limit) for b in budgets]


@router.post("/", response_model=BudgetSet, status_code=status.HTTP_201_CREATED)
def set_budget(
    body: BudgetSet,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = get_budget_for_category(db, current_user.id, body.category)

    if existing:
        existing.monthly_limit = body.monthly_limit
        db.add(existing)
    else:
        db.add(Budget(
            user_id=current_user.id,
            category=body.category,
            monthly_limit=body.monthly_limit,
        ))

    db.commit()
    return body


@router.get("/status", response_model=list[BudgetStatusItem])
def budget_status(
    month: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if month:
        y, m = int(month.split("-")[0]), int(month.split("-")[1])
        last = monthrange(y, m)[1]
        start, end = dt_date(y, m, 1), dt_date(y, m, last)
    else:
        start, end = current_month_range()

    budgets = get_user_budgets(db, current_user.id)
    if not budgets:
        return []

    spent_by_cat = category_breakdown(db, current_user.id, "expense", start, end)

    result = []
    for b in budgets:
        spent = spent_by_cat.get(b.category, 0.0)
        remaining = b.monthly_limit - spent
        percent = (spent / b.monthly_limit * 100) if b.monthly_limit > 0 else 0.0
        result.append(BudgetStatusItem(
            category=b.category,
            monthly_limit=round(b.monthly_limit, 2),
            spent=round(spent, 2),
            remaining=round(remaining, 2),
            percent_used=round(percent, 1),
        ))

    return sorted(result, key=lambda x: x.percent_used, reverse=True)


@router.get("/overspend", response_model=list[BudgetStatusItem])
def overspend(
    month: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    all_status = budget_status(month=month, current_user=current_user, db=db)
    return [item for item in all_status if item.spent > item.monthly_limit]