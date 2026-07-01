"""Budget tools — handler functions for setting and checking budgets.

Budget limits are stored in the Budget SQLModel table.
Spend data is queried from the Transaction table directly.
No bridge, no JSON file I/O.
"""

from calendar import monthrange
from datetime import datetime, date as dt_date

from sqlmodel import select, func

from core.models import Budget, Transaction, Category
from agent.utils import get_last_n_months


# ── Helpers ───────────────────────────────────────────────────────────────────

def _month_range(month: str) -> tuple[dt_date, dt_date]:
    year, mon = map(int, month.split("-"))
    last_day = monthrange(year, mon)[1]
    return dt_date(year, mon, 1), dt_date(year, mon, last_day)


def _get_spend_breakdown(db, user_id: int, month: str) -> dict[str, float]:
    """Return {category: total_expense} for the given month."""
    date_start, date_end = _month_range(month)
    rows = db.exec(
        select(Transaction.category, func.sum(Transaction.amount))
        .where(
            Transaction.user_id == user_id,
            Transaction.type == "expense",
            Transaction.date >= date_start,
            Transaction.date <= date_end,
        )
        .group_by(Transaction.category)
    ).all()
    return {cat: float(total) for cat, total in rows}


def _get_user_budgets(db, user_id: int) -> list[Budget]:
    """Return all Budget rows for this user."""
    return db.exec(select(Budget).where(Budget.user_id == user_id)).all()


def _get_budget_for_category(db, user_id: int, category: str) -> Budget | None:
    return db.exec(
        select(Budget).where(
            Budget.user_id == user_id,
            Budget.category == category,
        )
    ).first()


# ── Tool handlers ─────────────────────────────────────────────────────────────

def set_budget(args: dict, session) -> str:
    """Handle set_budget tool call — upsert a budget limit for a category."""
    try:
        db = session.db_session
        category = args["category"]
        limit = float(args["limit"])
        # month arg present in original schema but Budget table has no month scope in v1
        # we store per-category limits (not month-scoped); month arg is accepted but ignored
        month = args.get("month") or datetime.now().strftime("%Y-%m")

        existing = _get_budget_for_category(db, session.user_id, category)
        if existing:
            existing.monthly_limit = limit
            db.add(existing)
        else:
            db.add(Budget(user_id=session.user_id, category=category, monthly_limit=limit))
        db.commit()

        return f"Budget set — {category} monthly limit: ₹{limit:,.0f}"

    except Exception as e:
        return f"Error setting budget: {str(e)}"


def get_budget_status(args: dict, session) -> str:
    """Handle get_budget_status tool call."""
    try:
        db = session.db_session
        month = args.get("month") or datetime.now().strftime("%Y-%m")
        budgets = _get_user_budgets(db, session.user_id)

        if not budgets:
            return f"No budgets set"

        breakdown = _get_spend_breakdown(db, session.user_id, month)

        lines = []
        for b in budgets:
            spent = breakdown.get(b.category, 0)
            remaining = b.monthly_limit - spent
            percent = (spent / b.monthly_limit * 100) if b.monthly_limit > 0 else 0
            status = "⚠️ Over budget" if spent > b.monthly_limit else f"{percent:.0f}% used"
            lines.append(
                f"{b.category}: spent ₹{spent:,.0f} of ₹{b.monthly_limit:,.0f} "
                f"— {status}, remaining ₹{remaining:,.0f}"
            )

        return f"Budget status for {month} — " + " | ".join(lines)

    except Exception as e:
        return f"Error getting budget status: {str(e)}"


def check_overspend(args: dict, session) -> str:
    """Handle check_overspend tool call."""
    try:
        db = session.db_session
        month = args.get("month") or datetime.now().strftime("%Y-%m")
        budgets = _get_user_budgets(db, session.user_id)

        if not budgets:
            return "No budgets set"

        breakdown = _get_spend_breakdown(db, session.user_id, month)

        over = []
        warning = []

        for b in budgets:
            spent = breakdown.get(b.category, 0)
            percent = (spent / b.monthly_limit * 100) if b.monthly_limit > 0 else 0

            if spent > b.monthly_limit:
                over.append(
                    f"{b.category}: ₹{spent:,.0f} spent, ₹{b.monthly_limit:,.0f} limit "
                    f"(over by ₹{spent - b.monthly_limit:,.0f})"
                )
            elif percent >= 80:
                warning.append(
                    f"{b.category}: {percent:.0f}% used (₹{spent:,.0f} of ₹{b.monthly_limit:,.0f})"
                )

        if not over and not warning:
            return f"All categories within budget for {month} ✅"

        result = []
        if over:
            result.append(f"Over budget — {', '.join(over)}")
        if warning:
            result.append(f"Near limit — {', '.join(warning)}")
        return " | ".join(result)

    except Exception as e:
        return f"Error checking overspend: {str(e)}"


def suggest_budget(args: dict, session) -> str:
    """Suggest budget amounts based on last 3 months average spend per category."""
    try:
        db = session.db_session

        # get all expense categories for this user
        expense_cats = db.exec(
            select(Category).where(
                Category.user_id == session.user_id,
                Category.type == "expense",
            )
        ).all()

        past_months = get_last_n_months(3)
        suggestions = []

        for cat in expense_cats:
            totals = []
            for month in past_months:
                breakdown = _get_spend_breakdown(db, session.user_id, month)
                amount = breakdown.get(cat.name, 0)
                if amount > 0:
                    totals.append(amount)

            if totals:
                avg = sum(totals) / len(totals)
                # 10% buffer, rounded to nearest 100
                suggested = round(avg * 1.1 / 100) * 100
                suggestions.append(f"{cat.name}: ₹{suggested:,.0f} (avg ₹{avg:,.0f}/month)")

        if not suggestions:
            return "Not enough history to suggest budgets — need at least 1 month of data"

        return "Suggested budgets based on last 3 months — " + " | ".join(suggestions)

    except Exception as e:
        return f"Error getting budget suggestions: {str(e)}"