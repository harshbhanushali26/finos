"""
FinOS — analytics routes (api/routes/analytics.py)

GET /analytics/summary      — income, expense, balance for a period
GET /analytics/breakdown    — totals grouped by category
GET /analytics/top          — top N categories by amount
GET /analytics/chart/line   — time-series data for line chart
GET /analytics/chart/bar    — per-day or per-month totals for bar chart
"""

from calendar import monthrange
from collections import defaultdict
from datetime import timedelta, date as dt_date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select, func

from api.deps import get_current_user, get_db
from api.schemas import BreakdownItem, ChartPoint, SummaryResponse
from core.models import Transaction, User, Budget
from core.utils import get_last_n_months, current_month_range, month_range
from core.shared_analytics import sum_by_type


router = APIRouter(prefix="/analytics", tags=["analytics"])


# ── Health-Score ────────────────────────────────────────────────────────────────


@router.get("/calendar")
def calendar_data(
    month: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Per-day net total and transaction count for a given month.
    Returns { "2026-07-01": {"net": 120.5, "count": 3}, ... } for every
    day in the month (days with no transactions are included with 0/0).
    """
    start, end, _ = _get_date_range("monthly", month, None)
    txns = _fetch_transactions(current_user.id, start, end, "both", db)

    by_date: dict[dt_date, dict] = defaultdict(lambda: {"net": 0.0, "count": 0})
    for t in txns:
        sign = 1 if t.type == "income" else -1
        by_date[t.date]["net"] += sign * t.amount
        by_date[t.date]["count"] += 1

    result = {}
    current = start
    while current <= end:
        data = by_date[current]
        result[current.isoformat()] = {
            "net": round(data["net"], 2),
            "count": data["count"],
        }
        current += timedelta(days=1)

    return result



@router.get("/health-score")
def get_health_score(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cm_start, cm_end = current_month_range()

    current_income = sum_by_type(db, user.id, "income", cm_start, cm_end)
    current_expense = sum_by_type(db, user.id, "expense", cm_start, cm_end)

    savings_rate = round((current_income - current_expense) / current_income * 100, 1) if current_income > 0 else None

    budgets = db.exec(select(Budget).where(Budget.user_id == user.id)).all()
    if budgets:
        total_limit = sum(b.monthly_limit for b in budgets)
        spent_in_budgeted = 0.0
        for b in budgets:
            cat_spent = db.exec(
                select(func.sum(Transaction.amount)).where(
                    Transaction.user_id == user.id,
                    Transaction.type == "expense",
                    Transaction.category == b.category,
                    Transaction.date >= cm_start,
                    Transaction.date <= cm_end,
                )
            ).one()
            spent_in_budgeted += float(cat_spent or 0)
        budget_adherence = round(spent_in_budgeted / total_limit * 100, 1) if total_limit > 0 else None
    else:
        budget_adherence = None

    past_months = get_last_n_months(3)
    months_available = 0
    past_incomes = []
    past_expenses = []
    for m in past_months:
        date_start, date_end, _ = _get_date_range("monthly", m, None)
        inc = sum_by_type(db, user.id, "income", date_start, date_end)
        exp = sum_by_type(db, user.id, "expense", date_start, date_end)
        if inc > 0 or exp > 0:
            months_available += 1
        past_incomes.append(inc)
        past_expenses.append(exp)

    prev_month_income = past_incomes[-1] if past_incomes else 0
    prev_month_expense = past_expenses[-1] if past_expenses else 0

    income_stability = None
    expense_growth = None

    if months_available >= 1:
        expense_growth = round(current_expense / prev_month_expense * 100, 1) if prev_month_expense > 0 else None

        available_incomes = [i for i in past_incomes if i > 0]
        if available_incomes:
            avg_income = sum(available_incomes) / len(available_incomes)
            income_stability = round(current_income / avg_income * 100, 1) if avg_income > 0 else None

    return {
        "savings_rate": savings_rate,
        "budget_adherence": budget_adherence,
        "income_stability": income_stability,
        "expense_growth": expense_growth,
        "months_available": months_available,
    }


# ── Forecast ────────────────────────────────────────────────────────────────

@router.get("/forecast")
def get_forecast(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    past_months = get_last_n_months(3)

    monthly_totals = []
    for m in past_months:
        date_start, date_end, _ = _get_date_range("monthly", m, None)
        total = sum_by_type(db, user.id, "expense", date_start, date_end)
        monthly_totals.append({"month": m, "total": total})

    valid = [m["total"] for m in monthly_totals if m["total"] > 0]
    forecast = round(sum(valid) / len(valid), 2) if valid else 0.0

    cm_start, cm_end = current_month_range()
    current_spend = sum_by_type(db, user.id, "expense", cm_start, cm_end)

    return {
        "forecast": forecast,
        "based_on_months": monthly_totals,
        "current_month_spend_so_far": current_spend,
    }


# ── Helpers ────────────────────────────────────────────────────────────────

def _get_date_range(period: str, month: Optional[str], year: Optional[int]):
    """
    Resolve period string to (start_date, end_date, period_label).
    period: "weekly" | "monthly" | "yearly"
    """
    today = dt_date.today()

    if period == "weekly":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return start, end, f"{start.isoformat()} / {end.isoformat()}"

    elif period == "monthly":
        if month:
            try:
                y, m = int(month.split("-")[0]), int(month.split("-")[1])
            except (ValueError, IndexError):
                raise HTTPException(status_code=422, detail="month must be YYYY-MM")
        else:
            y, m = today.year, today.month

        month_str = f"{y}-{m:02d}"
        start, end = month_range(month_str)
        return start, end, month_str

    elif period == "yearly":
        y = int(year) if year else today.year
        return dt_date(y, 1, 1), dt_date(y, 12, 31), str(y)

    else:
        raise HTTPException(status_code=422, detail="period must be weekly, monthly, or yearly")


def _fetch_transactions(
    user_id: int,
    start: dt_date,
    end: dt_date,
    type_filter: Optional[str],
    db: Session,
) -> list[Transaction]:

    query = select(Transaction).where(
        Transaction.user_id == user_id,
        Transaction.date >= start,
        Transaction.date <= end,
    )

    if type_filter and type_filter != "both":
        query = query.where(Transaction.type == type_filter)
    return db.exec(query).all()


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=SummaryResponse)
def summary(
    period: str = "monthly",
    month: Optional[str] = None,
    year: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start, end, label = _get_date_range(period, month, year)
    txns = _fetch_transactions(current_user.id, start, end, "both", db)

    income = sum(t.amount for t in txns if t.type == "income")
    expense = sum(t.amount for t in txns if t.type == "expense")

    return SummaryResponse(
        income=round(income, 2),
        expense=round(expense, 2),
        balance=round(income - expense, 2),
        period=label,
    )


@router.get("/breakdown", response_model=list[BreakdownItem])
def breakdown(
    type: str = "expense",
    period: str = "monthly",
    month: Optional[str] = None,
    year: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start, end, _ = _get_date_range(period, month, year)
    txns = _fetch_transactions(current_user.id, start, end, type, db)

    totals: dict[str, float] = defaultdict(float)
    for t in txns:
        totals[t.category] += t.amount

    return [
        BreakdownItem(category=cat, total=round(total, 2))
        for cat, total in sorted(totals.items(), key=lambda x: x[1], reverse=True)
    ]


@router.get("/top", response_model=list[BreakdownItem])
def top_categories(
    type: str = "expense",
    n: int = 5,
    period: str = "monthly",
    month: Optional[str] = None,
    year: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start, end, _ = _get_date_range(period, month, year)
    txns = _fetch_transactions(current_user.id, start, end, type, db)

    totals: dict[str, float] = defaultdict(float)
    for t in txns:
        totals[t.category] += t.amount

    top = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:n]
    return [BreakdownItem(category=cat, total=round(total, 2)) for cat, total in top]


@router.get("/chart/line", response_model=list[ChartPoint])
def chart_line(
    period: str = "monthly",
    month: Optional[str] = None,
    year: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _build_chart_data(current_user.id, period, month, year, db)


@router.get("/chart/bar", response_model=list[ChartPoint])
def chart_bar(
    period: str = "monthly",
    month: Optional[str] = None,
    year: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _build_chart_data(current_user.id, period, month, year, db)


def _build_chart_data(
    user_id: int,
    period: str,
    month: Optional[str],
    year: Optional[int],
    db: Session,
) -> list[ChartPoint]:

    start, end, _ = _get_date_range(period, month, year)
    txns = _fetch_transactions(user_id, start, end, "both", db)

    by_date: dict[dt_date, dict] = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
    for t in txns:
        by_date[t.date][t.type] += t.amount

    points: list[ChartPoint] = []

    if period == "weekly":
        day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for i in range(7):
            d = start + timedelta(days=i)
            data = by_date[d]
            points.append(ChartPoint(
                label=day_labels[i],
                income=round(data["income"], 2),
                expense=round(data["expense"], 2),
            ))

    elif period == "monthly":
        current = start
        while current <= end:
            data = by_date[current]
            points.append(ChartPoint(
                label=f"{current.day:02d}",
                income=round(data["income"], 2),
                expense=round(data["expense"], 2),
            ))
            current += timedelta(days=1)

    elif period == "yearly":
        month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        monthly: dict[int, dict] = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
        for d, data in by_date.items():
            monthly[d.month]["income"] += data["income"]
            monthly[d.month]["expense"] += data["expense"]

        for m in range(1, 13):
            data = monthly[m]
            points.append(ChartPoint(
                label=month_labels[m - 1],
                income=round(data["income"], 2),
                expense=round(data["expense"], 2),
            ))

    return points