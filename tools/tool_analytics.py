"""Analytics tools — handler functions for summaries and category breakdowns.

All DB operations use session.db_session directly — no bridge.
"""

from datetime import datetime, date as dt_date

from sqlmodel import select

from core.models import Transaction
from core.utils import month_range
from core.shared_analytics import sum_by_type, category_breakdown


# ── Helpers ───────────────────────────────────────────────────────────────────

def _carry_forward(db, user_id: int, up_to: dt_date) -> float:
    """Net balance from all transactions before the given date."""
    from sqlmodel import func
    income = db.exec(
        select(func.sum(Transaction.amount)).where(
            Transaction.user_id == user_id,
            Transaction.type == "income",
            Transaction.date < up_to,
        )
    ).one()
    expense = db.exec(
        select(func.sum(Transaction.amount)).where(
            Transaction.user_id == user_id,
            Transaction.type == "expense",
            Transaction.date < up_to,
        )
    ).one()
    return float(income or 0) - float(expense or 0)


# ── Tool handlers ─────────────────────────────────────────────────────────────

def get_daily_summary(args: dict, session) -> str:
    """Handle get_daily_summary tool call."""
    try:
        db = session.db_session
        date_str = args["date"]
        day = datetime.strptime(date_str, "%Y-%m-%d").date()

        income = sum_by_type(db, session.user_id, "income", day, day)
        expense = sum_by_type(db, session.user_id, "expense", day, day)
        balance = income - expense
        carry_forward = _carry_forward(db, session.user_id, day)
        breakdown = category_breakdown(db, session.user_id, "expense", day, day)

        txns = db.exec(
            select(Transaction).where(
                Transaction.user_id == session.user_id,
                Transaction.date == day,
            )
        ).all()
        num_income = sum(1 for t in txns if t.type == "income")
        num_expense = sum(1 for t in txns if t.type == "expense")

        return (
            f"Daily summary for {date_str} — "
            f"Income: ₹{income:,.0f}, "
            f"Expense: ₹{expense:,.0f}, "
            f"Balance: ₹{balance:,.0f}, "
            f"Carry Forward: ₹{carry_forward:,.0f}, "
            f"Transactions: {num_income} income, {num_expense} expense, "
            f"Breakdown: {breakdown}"
        )

    except Exception as e:
        return f"Error getting daily summary: {str(e)}"


def get_monthly_summary(args: dict, session) -> str:
    """Handle get_monthly_summary tool call."""
    try:
        db = session.db_session
        month = args["month"]
        date_start, date_end = month_range(month)

        income = sum_by_type(db, session.user_id, "income", date_start, date_end)
        expense = sum_by_type(db, session.user_id, "expense", date_start, date_end)
        balance = income - expense
        carry_forward = _carry_forward(db, session.user_id, date_start)
        breakdown = category_breakdown(db, session.user_id, "expense", date_start, date_end)

        txns = db.exec(
            select(Transaction).where(
                Transaction.user_id == session.user_id,
                Transaction.date >= date_start,
                Transaction.date <= date_end,
            )
        ).all()
        num_income = sum(1 for t in txns if t.type == "income")
        num_expense = sum(1 for t in txns if t.type == "expense")

        return (
            f"Monthly summary for {month} — "
            f"Income: ₹{income:,.0f}, "
            f"Expense: ₹{expense:,.0f}, "
            f"Balance: ₹{balance:,.0f}, "
            f"Carry Forward: ₹{carry_forward:,.0f}, "
            f"Transactions: {num_income} income, {num_expense} expense, "
            f"Category breakdown: {breakdown}"
        )

    except Exception as e:
        return f"Error getting monthly summary: {str(e)}"


def get_category_breakdown(args: dict, session) -> str:
    """Handle get_category_breakdown tool call."""
    try:
        db = session.db_session
        txn_type = args.get("type") or args.get("type_")
        if not txn_type:
            return "Transaction type (income/expense) is required"

        month = args.get("month")
        if month:
            date_start, date_end = month_range(month)
        else:
            date_start = dt_date(2000, 1, 1)
            date_end = dt_date(2099, 12, 31)

        breakdown = category_breakdown(db, session.user_id, txn_type, date_start, date_end)

        if not breakdown:
            month_str = f" for {month}" if month else ""
            return f"No {txn_type} transactions found{month_str}"

        lines = [f"{cat}: ₹{amt:,.0f}" for cat, amt in breakdown.items()]
        month_str = f" for {month}" if month else " (all time)"
        return f"{txn_type.capitalize()} breakdown{month_str} — " + ", ".join(lines)

    except Exception as e:
        return f"Error getting category breakdown: {str(e)}"


def get_top_categories(args: dict, session) -> str:
    """Handle get_top_categories tool call."""
    try:
        db = session.db_session
        month = args["month"]
        top_n = args.get("top_n", 5)
        date_start, date_end = month_range(month)

        breakdown = category_breakdown(db, session.user_id, "expense", date_start, date_end)
        if not breakdown:
            return f"No expense data found for {month}"

        top = sorted(breakdown.items(), key=lambda x: x[1], reverse=True)[:top_n]
        lines = [f"{i+1}. {cat}: ₹{amt:,.0f}" for i, (cat, amt) in enumerate(top)]
        return f"Top {top_n} expense categories for {month} — " + ", ".join(lines)

    except Exception as e:
        return f"Error getting top categories: {str(e)}"


def get_categories(args: dict, session) -> str:
    """Handle get_categories tool call — returns all category names for this user."""
    try:
        from core.models import Category
        db = session.db_session

        rows = db.exec(
            select(Category).where(Category.user_id == session.user_id)
        ).all()

        income = [c.name for c in rows if c.type == "income"]
        expense = [c.name for c in rows if c.type == "expense"]

        return (
            f"Income categories: {', '.join(income) or 'none'} | "
            f"Expense categories: {', '.join(expense) or 'none'}"
        )

    except Exception as e:
        return f"Error getting categories: {str(e)}"