"""Insights routes — surfaces agent/insights.py detectors as dashboard cards.

GET /api/v1/insights — fixed monthly digest, independent of dashboard period filter.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from api.deps import get_db, get_current_user
from core.models import User
from agent.insights import (
    detect_spending_spikes,
    detect_subscriptions,
    detect_weekend_vs_weekday,
    detect_time_of_month,
    detect_lifestyle_inflation,
    detect_new_categories,
)

router = APIRouter(prefix="/insights", tags=["insights"])

# detector function -> (card type, severity)
DETECTOR_MAP = [
    (detect_spending_spikes, "spending_spike", "warning"),
    (detect_subscriptions, "subscription", "info"),
    (detect_weekend_vs_weekday, "weekend_pattern", "info"),
    (detect_time_of_month, "time_of_month", "info"),
    (detect_lifestyle_inflation, "lifestyle_inflation", "warning"),
    (detect_new_categories, "new_category", "info"),
]


def _current_month() -> str:
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


@router.get("/")
def get_insights(
    month: str | None = Query(default=None, description="YYYY-MM, defaults to current month"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    target_month = month or _current_month()

    cards = []
    for detector_fn, card_type, severity in DETECTOR_MAP:
        messages = detector_fn(db, user.id, target_month)
        for msg in messages:
            cards.append({
                "type": card_type,
                "severity": severity,
                "message": msg,
            })

    return {"insights": cards, "month": target_month}