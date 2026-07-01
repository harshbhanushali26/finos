"""
Pattern Matcher — Phase A
Intercepts simple user messages before they reach the LLM.

Match families:
    1. Balance — "balance", "my balance", "how much left"
    2. View    — "show this month", "transactions today", "list january"
    3. Add     — "add 250 food", "spent 2.5k on transport", "got 50000 salary"

Returns:
    {"matched": True,  "response": "<formatted string>"}
    {"matched": False}

If anything is ambiguous, returns {"matched": False} — LLM handles it.
All DB access uses session.db_session directly — no bridge, no JSON file reads.
"""

import re
from calendar import month_name, monthrange
from datetime import date, timedelta

from sqlmodel import select, func

from core.models import Transaction, User, Budget, Category



# ── Constants ──────────────────────────────────────────────────────────────────

INCOME_TRIGGERS  = {"got", "received", "income", "earned", "credited"}
EXPENSE_TRIGGERS = {"spent", "spend", "paid", "pay", "bought", "buy", "added", "add", "expense"}
ALL_TRIGGERS     = INCOME_TRIGGERS | EXPENSE_TRIGGERS

VIEW_TRIGGERS = {"show", "view", "list", "display", "see"}
VIEW_PHRASES  = {"what did i spend", "show me", "show my", "list my", "my transactions"}

BALANCE_PHRASES = {
    "balance", "my balance", "overview", "dashboard",
    "how much do i have", "how much left", "how much do i have left",
    "what's my balance", "whats my balance"
}

BUDGET_PHRASES = {"budget", "budgets", "budget status", "my budget", "show budget"}
CATEGORY_PHRASES = {"categories", "category list", "show categories", "my categories"}
INSIGHTS_PHRASES = {"insights", "analyse", "analyze", "smart insights", "analysis"}

STOP_WORDS = {"a", "an", "the", "my", "me", "i", "it", "this", "that", "and", "in", "to"}

DATE_WORDS = {
    "today", "yesterday",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december"
}

LIST_PHRASES = {
    "all expenses", "all income", "all transactions",
    "list all", "show all", "list food", "list rent",
    "list utilities", "list transport", "list shopping",
    "food transactions", "rent transactions"
}

CONFIG_PHRASES    = {"config", "settings", "preference", "income setting", "currency setting"}
ANALYTICS_KEYWORDS = {"top", "breakdown", "pattern", "analysis", "compare", "trend"}

REJECTED_CATEGORY_WORDS = STOP_WORDS | DATE_WORDS | ALL_TRIGGERS

MONTH_MAP = {name.lower(): f"{i:02d}" for i, name in enumerate(month_name) if name}

DEBUG = False


# ── Public entry point ─────────────────────────────────────────────────────────

def match(user_message: str, session) -> dict:
    """Try to match user_message against known patterns.

    Returns {"matched": True, "response": str} or {"matched": False}.
    session.db_session is used for all DB queries.
    """
    original   = user_message.strip()
    normalized = original.lower()

    if "?" in original:
        if DEBUG: print("[PM] ✗ bail — question mark")
        return {"matched": False}

    if _has_multiple_clauses(normalized):
        if DEBUG: print("[PM] ✗ bail — multiple clauses")
        return {"matched": False}

    if _is_balance_query(normalized):
        if DEBUG: print("[PM] ✓ matched — balance")
        return _handle_balance(session)

    if normalized in BUDGET_PHRASES:
        return _handle_budget(session)

    if normalized in CATEGORY_PHRASES:
        return _handle_categories(session)

    if normalized in INSIGHTS_PHRASES:
        return _handle_insights(session)

    if _is_view_query(normalized):
        if DEBUG: print("[PM] ✓ matched — view")
        return _handle_view(normalized, session)

    if _is_add_query(normalized):
        if DEBUG: print("[PM] ✓ matched — add")
        return _handle_add(original, normalized, session)

    if DEBUG: print("[PM] ✗ no match — falling to LLM")
    return {"matched": False}


# ── Guard helpers ──────────────────────────────────────────────────────────────

def _has_multiple_clauses(normalized: str) -> bool:
    clause_words = r"\b(but|although|however|also|and then|then delete|then update|except)\b"
    return bool(re.search(clause_words, normalized))


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _get_currency(session) -> str:
    """Read currency from User table. Falls back to ₹."""
    try:
        db = session.db_session
        user = db.get(User, session.user_id)
        symbol_map = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}
        code = user.currency if user else "INR"
        return symbol_map.get(code, code + " ")
    except Exception:
        return "₹"


def _monthly_summary(db, user_id: int, month: str) -> dict:
    """Return {income, expense, num_income, num_expense} for a month."""
    year, mon = map(int, month.split("-"))
    last_day = monthrange(year, mon)[1]
    d_start = date(year, mon, 1)
    d_end   = date(year, mon, last_day)

    def _sum(txn_type):
        result = db.exec(
            select(func.sum(Transaction.amount)).where(
                Transaction.user_id == user_id,
                Transaction.type == txn_type,
                Transaction.date >= d_start,
                Transaction.date <= d_end,
            )
        ).one()
        return float(result or 0)

    def _count(txn_type):
        result = db.exec(
            select(func.count(Transaction.id)).where(
                Transaction.user_id == user_id,
                Transaction.type == txn_type,
                Transaction.date >= d_start,
                Transaction.date <= d_end,
            )
        ).one()
        return int(result or 0)

    income  = _sum("income")
    expense = _sum("expense")
    return {
        "income":      income,
        "expense":     expense,
        "balance":     income - expense,
        "num_income":  _count("income"),
        "num_expense": _count("expense"),
    }


def _daily_summary(db, user_id: int, day: date) -> dict:
    """Return {income, expense, num_income, num_expense} for a single day."""
    def _sum(txn_type):
        result = db.exec(
            select(func.sum(Transaction.amount)).where(
                Transaction.user_id == user_id,
                Transaction.type == txn_type,
                Transaction.date == day,
            )
        ).one()
        return float(result or 0)

    def _count(txn_type):
        result = db.exec(
            select(func.count(Transaction.id)).where(
                Transaction.user_id == user_id,
                Transaction.type == txn_type,
                Transaction.date == day,
            )
        ).one()
        return int(result or 0)

    income  = _sum("income")
    expense = _sum("expense")
    return {
        "income":      income,
        "expense":     expense,
        "num_income":  _count("income"),
        "num_expense": _count("expense"),
    }


def _category_breakdown(db, user_id: int, txn_type: str, month: str) -> dict[str, float]:
    """Return {category: total} for a user/type/month."""
    year, mon = map(int, month.split("-"))
    last_day = monthrange(year, mon)[1]
    d_start = date(year, mon, 1)
    d_end   = date(year, mon, last_day)

    rows = db.exec(
        select(Transaction.category, func.sum(Transaction.amount))
        .where(
            Transaction.user_id == user_id,
            Transaction.type == txn_type,
            Transaction.date >= d_start,
            Transaction.date <= d_end,
        )
        .group_by(Transaction.category)
    ).all()
    return {cat: float(total) for cat, total in rows}


def _add_transaction(db, user_id: int, txn_type: str, amount: float,
                        category: str, txn_date: str, note: str | None) -> dict:
    """Insert a transaction. Returns {"success": True} or {"success": False, "error": ...}."""
    from core.models import Category
    from datetime import datetime as dt

    try:
        parsed_date = dt.strptime(txn_date, "%Y-%m-%d").date()

        # ensure category exists
        existing_cat = db.exec(
            select(Category).where(
                Category.user_id == user_id,
                Category.name == category,
                Category.type == txn_type,
            )
        ).first()
        if not existing_cat:
            db.add(Category(user_id=user_id, name=category, type=txn_type, is_default=False))
            db.commit()

        # duplicate check
        duplicate = db.exec(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.type == txn_type,
                Transaction.amount == amount,
                Transaction.category == category,
                Transaction.date == parsed_date,
            )
        ).first()

        txn = Transaction(
            user_id=user_id,
            amount=amount,
            type=txn_type,
            category=category,
            date=parsed_date,
            note=note or "",
        )
        db.add(txn)
        db.commit()

        return {"success": True, "warning": "possible duplicate" if duplicate else None}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Budget ─────────────────────────────────────────────────────────────────────

def _handle_budget(session) -> dict:
    try:
        db = session.db_session
        uid = session.user_id
        today = date.today()
        month_start = date(today.year, today.month, 1)
        budgets = session.db_session.exec(select(Budget).where(Budget.user_id == uid)).all()
        if not budgets:
            return {"matched": True, "response": "No budgets set yet. Use the Budget page to add limits."}
        txns = db.exec(select(Transaction).where(
            Transaction.user_id == uid,
            Transaction.type == "expense",
            Transaction.date >= month_start,
            Transaction.date <= today
        )).all()
        spent_by_cat = {}
        for t in txns:
            spent_by_cat[t.category] = spent_by_cat.get(t.category, 0) + t.amount
        currency = _get_currency(session)
        lines = []
        for b in budgets:
            spent = spent_by_cat.get(b.category, 0)
            pct = (spent / b.monthly_limit * 100) if b.monthly_limit else 0
            status = "🔴 OVER" if pct >= 100 else "🟡 warn" if pct >= 80 else "🟢 ok"
            lines.append(f"{b.category}: {currency}{spent:,.0f} / {currency}{b.monthly_limit:,.0f} ({pct:.0f}%) {status}")
        return {"matched": True, "response": "Budget Status:\n" + "\n".join(lines)}
    except Exception:
        return {"matched": False}


# ── Categories ─────────────────────────────────────────────────────────────────

def _handle_categories(session) -> dict:
    try:
        cats = session.db_session.exec(
            select(Category).where(Category.user_id == session.user_id)
        ).all()
        if not cats:
            return {"matched": True, "response": "No categories found."}
        exp = [c.name for c in cats if c.type == "expense"]
        inc = [c.name for c in cats if c.type == "income"]
        parts = []
        if exp: parts.append("Expense: " + ", ".join(exp))
        if inc: parts.append("Income: " + ", ".join(inc))
        return {"matched": True, "response": "Categories — " + " | ".join(parts)}
    except Exception:
        return {"matched": False}


# ── Insights ───────────────────────────────────────────────────────────────────

def _handle_insights(session) -> dict:
    try:
        from agent.insights import run_all
        today = date.today()
        month_str = today.strftime("%Y-%m")
        results = run_all(session.db_session, session.user_id, month_str)
        if not results:
            return {"matched": True, "response": "No insights detected for this month yet — add more transactions to get patterns."}
        return {"matched": True, "response": "Insights:\n" + "\n".join(results)}
    except Exception:
        return {"matched": False}


# ── Balance ────────────────────────────────────────────────────────────────────

def _is_balance_query(normalized: str) -> bool:
    return normalized in BALANCE_PHRASES


def _handle_balance(session) -> dict:
    try:
        today     = date.today()
        month_str = today.strftime("%Y-%m")
        db        = session.db_session
        summary   = _monthly_summary(db, session.user_id, month_str)
        currency  = _get_currency(session)

        month_label = today.strftime("%B %Y")
        response = (
            f"{month_label} — "
            f"Income: {currency}{summary['income']:,.0f}  |  "
            f"Expenses: {currency}{summary['expense']:,.0f}  |  "
            f"Balance: {currency}{summary['balance']:,.0f}"
        )
        return {"matched": True, "response": response}
    except Exception:
        return {"matched": False}


# ── View ───────────────────────────────────────────────────────────────────────

def _is_view_query(normalized: str) -> bool:
    if any(phrase in normalized for phrase in LIST_PHRASES):
        return False
    if any(word in normalized for word in CONFIG_PHRASES):
        return False
    if any(word in normalized.split() for word in ANALYTICS_KEYWORDS):
        return False
    if any(normalized.startswith(t) for t in VIEW_TRIGGERS):
        return True
    if any(phrase in normalized for phrase in VIEW_PHRASES):
        return True
    if normalized in {"transactions", "my transactions", "this month", "last month"}:
        return True
    return False


def _handle_view(normalized: str, session) -> dict:
    try:
        period   = _extract_period(normalized)
        if period is None:
            return {"matched": False}

        db       = session.db_session
        currency = _get_currency(session)

        if period["type"] == "day":
            day_str = period["value"]
            day     = date.fromisoformat(day_str)
            summary = _daily_summary(db, session.user_id, day)
            label   = "Today" if day == date.today() else "Yesterday"
            txn_count = summary["num_income"] + summary["num_expense"]

            response = (
                f"{label} ({day_str}) — "
                f"Income: {currency}{summary['income']:,.0f}  |  "
                f"Expenses: {currency}{summary['expense']:,.0f}  |  "
                f"{txn_count} transaction(s)"
            )
            return {"matched": True, "response": response}

        elif period["type"] == "month":
            month_str = period["value"]
            summary   = _monthly_summary(db, session.user_id, month_str)
            year, mon = month_str.split("-")
            label     = f"{month_name[int(mon)]} {year}"
            txn_count = summary["num_income"] + summary["num_expense"]

            response = (
                f"{label} — "
                f"Income: {currency}{summary['income']:,.0f}  |  "
                f"Expenses: {currency}{summary['expense']:,.0f}  |  "
                f"Balance: {currency}{summary['balance']:,.0f}  |  "
                f"{txn_count} transaction(s)"
            )
            return {"matched": True, "response": response}

    except Exception:
        return {"matched": False}

    return {"matched": False}


def _extract_period(normalized: str) -> dict | None:
    today = date.today()

    if "today" in normalized:
        return {"type": "day", "value": str(today)}
    if "yesterday" in normalized:
        return {"type": "day", "value": str(today - timedelta(days=1))}
    if "this month" in normalized or normalized in {"transactions", "my transactions"}:
        return {"type": "month", "value": today.strftime("%Y-%m")}
    if "last month" in normalized:
        first_of_this = today.replace(day=1)
        last_month    = first_of_this - timedelta(days=1)
        return {"type": "month", "value": last_month.strftime("%Y-%m")}

    for mon_name, mon_num in MONTH_MAP.items():
        if mon_name in normalized:
            year_match = re.search(r"\b(20\d{2})\b", normalized)
            year = year_match.group(1) if year_match else str(today.year)
            return {"type": "month", "value": f"{year}-{mon_num}"}

    ambiguous = r"\b(week|ago|recent|latest|past|monday|tuesday|wednesday|thursday|friday|saturday|sunday|last)\b"
    if re.search(ambiguous, normalized):
        return None

    return {"type": "month", "value": today.strftime("%Y-%m")}


# ── Add ────────────────────────────────────────────────────────────────────────

def _is_add_query(normalized: str) -> bool:
    first_word = normalized.split()[0] if normalized.split() else ""
    return first_word in ALL_TRIGGERS


def _handle_add(original: str, normalized: str, session) -> dict:
    try:
        note             = None
        original_clean   = original
        normalized_clean = normalized

        if " note " in normalized:
            parts            = normalized.split(" note ", 1)
            normalized_clean = parts[0].strip()
            note             = parts[1].strip()
            original_clean   = original[:original.lower().index(" note ")].strip()

        txn_type = _extract_type(normalized_clean)
        if txn_type is None:
            return {"matched": False}

        amount = _extract_amount(normalized_clean)
        if amount is None:
            return {"matched": False}

        category = _extract_category(original_clean)
        if category is None:
            return {"matched": False}

        txn_date = _extract_date(normalized_clean)
        if txn_date is None:
            return {"matched": False}

        db     = session.db_session
        result = _add_transaction(db, session.user_id, txn_type, amount, category, txn_date, note)

        if not result.get("success"):
            return {"matched": False}

        if result.get("warning") == "possible duplicate":
            return {"matched": False}

        # build response with category total for this month
        currency  = _get_currency(session)
        month_str = txn_date[:7]
        breakdown = _category_breakdown(db, session.user_id, txn_type, month_str)
        cat_total = breakdown.get(category.title(), 0)

        date_obj   = date.fromisoformat(txn_date)
        date_label = (
            "today"     if date_obj == date.today()
            else "yesterday" if date_obj == date.today() - timedelta(days=1)
            else date_obj.strftime("%b %d")
        )

        type_label = "income" if txn_type == "income" else "expense"
        response   = (
            f"Added {currency}{amount:,.0f} for {category.title()} {date_label}. "
            f"{category.title()} {type_label} this month: {currency}{cat_total:,.0f}."
        )
        return {"matched": True, "response": response}

    except Exception as e:
        if DEBUG: print(f"[PM] ✗ exception in _handle_add: {e}")
        return {"matched": False}


# ── Extraction helpers ─────────────────────────────────────────────────────────

def _extract_type(normalized: str) -> str | None:
    first_word = normalized.split()[0] if normalized.split() else ""
    if first_word in INCOME_TRIGGERS:
        return "income"
    if first_word in EXPENSE_TRIGGERS:
        return "expense"
    return None


def _extract_amount(normalized: str) -> float | None:
    m = re.search(r"\b(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)([kK])?\b", normalized)
    if not m:
        return None
    raw    = m.group(1).replace(",", "")
    suffix = m.group(2)
    try:
        value = float(raw)
    except ValueError:
        return None
    if suffix and suffix.lower() == "k":
        value *= 1000
    return value if value > 0 else None


def _extract_category(original: str) -> str | None:
    normalized = original.lower()

    def is_valid(word: str) -> bool:
        return word.lower() not in REJECTED_CATEGORY_WORDS and word.isalpha()

    def has_next_content_word(text: str, match_end: int) -> bool:
        rest   = text[match_end:].strip()
        next_m = re.match(r"([A-Za-z]+)", rest)
        return bool(next_m and is_valid(next_m.group(1)))

    for prep in ("for", "on", "from", "as"):
        pattern = rf"\b{prep}\s+([A-Za-z]+)\b"
        m = re.search(pattern, original, re.IGNORECASE)
        if m:
            word = m.group(1)
            if is_valid(word):
                if has_next_content_word(original, m.end()):
                    return None
                return word

    amount_pattern = r"\b\d[\d,\.]*[kK]?\b"
    m = re.search(rf"(?:{amount_pattern})\s+([A-Za-z]+)\b", original)
    if m:
        word = m.group(1)
        if is_valid(word):
            if has_next_content_word(original, m.end()):
                return None
            return word

    return None


def _extract_date(normalized: str) -> str | None:
    today = date.today()

    if "yesterday" in normalized:
        return str(today - timedelta(days=1))

    iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", normalized)
    if iso:
        return iso.group(1)

    ambiguous = r"\b(last|next|previous|monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|ago)\b"
    if re.search(ambiguous, normalized):
        return None

    return str(today)