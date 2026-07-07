"""
core/shared_txns.py

Shared low-level DB operations for Transaction and Category, used by:
- api/routes/transactions.py
- api/routes/categories.py
- tools/tool_transactions.py
- agent/pattern_matcher.py

Each caller keeps its own policy (missing-category behavior, duplicate-name
rejection vs. confirm-to-create, error handling, response formatting).
This file only owns the raw queries/inserts that were previously
duplicated identically across callers.
"""

from datetime import date as dt_date
from sqlmodel import select

from core.models import Category, PaymentMethod, Transaction


def category_exists(db, user_id: int, name: str, type_: str) -> bool:
    """True if a category with this name/type already exists for the user."""
    return db.exec(
        select(Category).where(
            Category.user_id == user_id,
            Category.name == name,
            Category.type == type_,
        )
    ).first() is not None


def payment_method_exists(db, user_id: int, name: str) -> bool:
    """True if a payment method with this name already exists for the user."""
    return db.exec(
        select(PaymentMethod).where(
            PaymentMethod.user_id == user_id,
            PaymentMethod.name == name,
        )
    ).first() is not None


def find_duplicate(db, user_id: int, type_: str, amount: float,
                    category: str, txn_date: dt_date) -> Transaction | None:
    """Exact-match check: same user/type/amount/category/date. None if no match."""
    return db.exec(
        select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.type == type_,
            Transaction.amount == amount,
            Transaction.category == category,
            Transaction.date == txn_date,
        )
    ).first()


def get_owned_transaction(db, user_id: int, txn_id: int) -> Transaction | None:
    """Fetch a transaction by id, but only if it belongs to this user."""
    txn = db.get(Transaction, txn_id)
    if not txn or txn.user_id != user_id:
        return None
    return txn


def get_owned_category(db, user_id: int, category_id: int) -> Category | None:
    """Fetch a category by id, but only if it belongs to this user."""
    cat = db.get(Category, category_id)
    if not cat or cat.user_id != user_id:
        return None
    return cat


def insert_transaction(db, user_id: int, type_: str, amount: float, category: str,
                        txn_date: dt_date, note: str = "",
                        payment_method: str | None = None) -> Transaction:
    """Insert and commit. Caller must validate category/payment_method existence
    and check duplicates beforehand — this function just writes the row."""
    txn = Transaction(
        user_id=user_id,
        amount=amount,
        type=type_,
        category=category,
        payment_method=payment_method,
        date=txn_date,
        note=note,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn