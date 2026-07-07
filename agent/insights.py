"""Insight detectors — pattern analysis on transaction history.

Six detectors, each receiving (db, user_id, month) instead of bridge.
All DB access is direct SQLModel queries — no bridge.

run_all(db, user_id, month) — entry point called by agent/core.py or pattern_matcher.
"""

from calendar import monthrange
from datetime import date

from sqlmodel import select

from core.models import Transaction
from core.utils import month_range
from core.shared_analytics import category_breakdown, sum_by_type
from agent.utils import get_last_n_months


# ── Shared query helpers ───────────────────────────────────────────────────────

def _get_category_breakdown(db, user_id: int, txn_type: str, month: str) -> dict[str, float]:
    """Return {category: total} for a user/type/month."""
    date_start, date_end = month_range(month)
    return category_breakdown(db, user_id, txn_type, date_start, date_end)


def _get_expense_transactions(db, user_id: int, month: str) -> list[Transaction]:
    """Return all expense transactions for a user/month."""
    date_start, date_end = month_range(month)
    return db.exec(
        select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.type == "expense",
            Transaction.date >= date_start,
            Transaction.date <= date_end,
        )
    ).all()


def _get_monthly_expense_total(db, user_id: int, month: str) -> float:
    """Return total expense amount for a user/month."""
    date_start, date_end = month_range(month)
    return sum_by_type(db, user_id, "expense", date_start, date_end)


# ── Detector 1 — spending spikes ──────────────────────────────────────────────

def detect_spending_spikes(db, user_id: int, month: str) -> list[str]:
    """Detect categories where current month spend is 2x higher than 3-month average."""
    try:
        past_months = get_last_n_months(3)
        past_breakdowns = [_get_category_breakdown(db, user_id, "expense", m) for m in past_months]

        months_with_data = [b for b in past_breakdowns if b]
        if len(months_with_data) < 2:
            return []

        current_breakdown = _get_category_breakdown(db, user_id, "expense", month)
        if not current_breakdown:
            return []

        insights = []
        for category, current_amt in current_breakdown.items():
            past_amounts = [b.get(category, 0) for b in past_breakdowns]
            past_avg = sum(past_amounts) / len(past_breakdowns)
            if past_avg == 0:
                continue
            ratio = current_amt / past_avg
            if ratio >= 2.0:
                insights.append(
                    f"⚠ {category} spend (₹{current_amt:,.0f}) is "
                    f"{ratio:.1f}x your 3-month average (₹{past_avg:,.0f})"
                )
        return insights

    except Exception:
        return []


# ── Detector 2 — subscription creep ──────────────────────────────────────────

def detect_subscriptions(db, user_id: int, month: str) -> list[str]:
    """Detect recurring transactions — same category + similar amount for 3 months."""
    try:
        past_months = get_last_n_months(3)
        if len(past_months) < 3:
            return []

        monthly_txns = [_get_expense_transactions(db, user_id, m) for m in past_months]
        if any(len(t) == 0 for t in monthly_txns):
            return []

        cat_amounts: dict[str, list[float]] = {}
        for month_txns in monthly_txns:
            seen: dict[str, float] = {}
            for txn in month_txns:
                seen[txn.category] = seen.get(txn.category, 0) + txn.amount
            for cat, amt in seen.items():
                cat_amounts.setdefault(cat, []).append(amt)

        insights = []
        for category, amounts in cat_amounts.items():
            if len(amounts) < 3:
                continue
            min_amt = min(amounts)
            max_amt = max(amounts)
            if min_amt == 0:
                continue
            variation = (max_amt - min_amt) / min_amt
            if variation <= 0.05:
                avg_amt = sum(amounts) / len(amounts)
                insights.append(
                    f"↻ Possible subscription: ₹{avg_amt:,.0f} {category} "
                    f"— recurring for 3 months"
                )
        return insights

    except Exception:
        return []


# ── Detector 3 — weekend vs weekday ──────────────────────────────────────────

def detect_weekend_vs_weekday(db, user_id: int, month: str) -> list[str]:
    """Compare average daily spend on weekends vs weekdays."""
    try:
        txns = _get_expense_transactions(db, user_id, month)
        if not txns:
            return []

        weekend_total = 0.0
        weekday_total = 0.0

        for txn in txns:
            day_of_week = txn.date.weekday()
            if day_of_week >= 5:
                weekend_total += txn.amount
            else:
                weekday_total += txn.amount

        year, mon = map(int, month.split("-"))
        total_days = monthrange(year, mon)[1]
        weekend_days = sum(
            1 for d in range(1, total_days + 1)
            if date(year, mon, d).weekday() >= 5
        )
        weekday_days = total_days - weekend_days

        if weekend_days == 0 or weekday_days == 0:
            return []

        daily_weekend = weekend_total / weekend_days
        daily_weekday = weekday_total / weekday_days

        if daily_weekday == 0:
            return []

        ratio = daily_weekend / daily_weekday
        if ratio >= 1.5:
            return [
                f"📅 You spend {ratio:.1f}x more on weekends "
                f"(₹{daily_weekend:,.0f}/day vs ₹{daily_weekday:,.0f}/day weekdays)"
            ]
        return []

    except Exception:
        return []


# ── Detector 4 — time of month ────────────────────────────────────────────────

def detect_time_of_month(db, user_id: int, month: str) -> list[str]:
    """Detect which third of the month has highest spending."""
    try:
        txns = _get_expense_transactions(db, user_id, month)
        if not txns:
            return []

        year, mon = map(int, month.split("-"))
        total_days = monthrange(year, mon)[1]

        part1 = part2 = part3 = 0.0
        for txn in txns:
            day = txn.date.day
            if day <= 10:
                part1 += txn.amount
            elif day <= 20:
                part2 += txn.amount
            else:
                part3 += txn.amount

        total = part1 + part2 + part3
        if total == 0:
            return []

        parts = {
            "first 10 days": part1,
            "middle 10 days": part2,
            f"last {total_days - 20} days": part3,
        }
        max_part = max(parts, key=parts.get)
        pct = (parts[max_part] / total) * 100

        if pct >= 50:
            return [f"📆 {pct:.0f}% of your spending happens in the {max_part} of the month"]
        return []

    except Exception:
        return []


# ── Detector 5 — lifestyle inflation ─────────────────────────────────────────

def detect_lifestyle_inflation(db, user_id: int, month: str) -> list[str]:
    """Detect month-over-month expense growth trend."""
    try:
        past_months = get_last_n_months(3)
        if len(past_months) < 2:
            return []

        months_ordered = list(reversed(past_months)) + [month]
        expenses = [_get_monthly_expense_total(db, user_id, m) for m in months_ordered]

        months_with_data = [e for e in expenses if e > 0]
        if len(months_with_data) < 2:
            return []

        oldest = expenses[0]
        newest = expenses[-1]
        if oldest == 0:
            return []

        overall_growth = (newest - oldest) / oldest * 100
        if overall_growth >= 10:
            trend_parts = [f"₹{e:,.0f}" for e in expenses if e > 0]
            trend_str = " → ".join(trend_parts)
            return [
                f"📈 Monthly expenses grew {overall_growth:.0f}% over last 3 months "
                f"({trend_str})"
            ]
        return []

    except Exception:
        return []


# ── Detector 6 — new categories ───────────────────────────────────────────────

def detect_new_categories(db, user_id: int, month: str) -> list[str]:
    """Detect expense categories that appear this month but not last month."""
    try:
        past_months = get_last_n_months(1)
        last_month = past_months[0]

        this_cats = set(_get_category_breakdown(db, user_id, "expense", month).keys())
        last_cats = set(_get_category_breakdown(db, user_id, "expense", last_month).keys())

        new_cats = this_cats - last_cats
        if not new_cats:
            return []

        cats_str = ", ".join(sorted(new_cats))
        return [f"🆕 First time spending this month on: {cats_str}"]

    except Exception:
        return []


# ── Entry point ───────────────────────────────────────────────────────────────

def run_all(db, user_id: int, month: str) -> list[str]:
    """Run all detectors and return combined insights."""
    detectors = [
        detect_spending_spikes,
        detect_subscriptions,
        detect_weekend_vs_weekday,
        detect_time_of_month,
        detect_lifestyle_inflation,
        detect_new_categories,
    ]

    insights = []
    for detector in detectors:
        try:
            results = detector(db, user_id, month)
            insights.extend(results)
        except Exception:
            continue

    return insights