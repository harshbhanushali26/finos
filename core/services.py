"""
core/services.py — Central Transaction Service Layer for FinOS.

Encapsulates all transaction business logic:
- Validation (category existence, payment method existence, type, amounts)
- Duplicate checking
- Shared query building and candidate filtering
- Database operations (create, read/filter, update, delete)

All functions return strongly-typed dataclasses with a ServiceStatus enum.
They never raise HTTP exceptions or return formatted natural language strings.
"""

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date as dt_date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from core import shared_txns
from core.models import Category, PaymentMethod, Transaction


# ── Status Enums ───────────────────────────────────────────────────────────────

class ServiceStatus(str, Enum):
    SUCCESS = "success"
    CREATED = "created"
    NOT_FOUND = "not_found"
    VALIDATION_ERROR = "validation_error"
    CATEGORY_NOT_FOUND = "category_not_found"
    PAYMENT_METHOD_NOT_FOUND = "payment_method_not_found"
    DUPLICATE_DETECTED = "duplicate_detected"
    TOO_MANY_CANDIDATES = "too_many_candidates"
    NO_FIELDS_TO_UPDATE = "no_fields_to_update"


# ── Result Dataclasses ─────────────────────────────────────────────────────────

@dataclass
class CreateResult:
    """Result of create_transaction operation."""
    status: ServiceStatus
    transaction: Optional[Transaction] = None
    is_duplicate: bool = False
    duplicate_of: Optional[Transaction] = None
    missing_category: Optional[str] = None
    missing_payment_method: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class UpdateResult:
    """Result of update_transaction operation."""
    status: ServiceStatus
    transaction: Optional[Transaction] = None
    updated_fields: Dict[str, Any] = field(default_factory=dict)
    missing_category: Optional[str] = None
    missing_payment_method: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class DeleteResult:
    """Result of delete_transaction operation."""
    status: ServiceStatus
    deleted_id: Optional[int] = None
    error_message: Optional[str] = None


@dataclass
class TransactionListResult:
    """Result of get_transactions query operation."""
    status: ServiceStatus
    transactions: List[Transaction] = field(default_factory=list)
    total_count: int = 0
    error_message: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(date_val: dt_date | str) -> dt_date:
    """Normalize a date object or YYYY-MM-DD string into a date object."""
    if isinstance(date_val, dt_date):
        return date_val
    return datetime.strptime(date_val, "%Y-%m-%d").date()


def ensure_category(db: Session, user_id: int, name: str, type_: str) -> Category:
    """Create category if it does not already exist for this user. Returns Category."""
    existing = db.exec(
        select(Category).where(
            Category.user_id == user_id,
            Category.name == name,
            Category.type == type_,
        )
    ).first()
    if existing:
        return existing

    category = Category(user_id=user_id, name=name, type=type_, is_default=False)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def ensure_payment_method(db: Session, user_id: int, name: str) -> PaymentMethod:
    """Create payment method if it does not already exist for this user. Returns PaymentMethod."""
    existing = db.exec(
        select(PaymentMethod).where(
            PaymentMethod.user_id == user_id,
            PaymentMethod.name == name,
        )
    ).first()
    if existing:
        return existing

    pm = PaymentMethod(user_id=user_id, name=name, is_default=False)
    db.add(pm)
    db.commit()
    db.refresh(pm)
    return pm


# ── Core Operations ───────────────────────────────────────────────────────────

def create_transaction(
    db: Session,
    user_id: int,
    *,
    type_: str,
    amount: float,
    category: str,
    date: dt_date | str,
    note: str = "",
    payment_method: Optional[str] = None,
    allow_create_category: bool = False,
    allow_create_payment_method: bool = False,
) -> CreateResult:
    """Validate inputs, check duplicates, and insert a new transaction."""
    if type_ not in ("income", "expense"):
        return CreateResult(
            status=ServiceStatus.VALIDATION_ERROR,
            error_message="type must be 'income' or 'expense'",
        )

    if amount <= 0:
        return CreateResult(
            status=ServiceStatus.VALIDATION_ERROR,
            error_message="amount must be greater than zero",
        )

    try:
        parsed_date = _parse_date(date)
    except (ValueError, TypeError) as e:
        return CreateResult(
            status=ServiceStatus.VALIDATION_ERROR,
            error_message=f"Invalid date format: {e}",
        )

    # 1. Category validation / auto-creation
    if not shared_txns.category_exists(db, user_id, category, type_):
        if allow_create_category:
            ensure_category(db, user_id, category, type_)
        else:
            return CreateResult(
                status=ServiceStatus.CATEGORY_NOT_FOUND,
                missing_category=category,
                error_message=f"Category '{category}' does not exist for type '{type_}'",
            )

    # 2. Payment method validation / auto-creation
    if payment_method:
        if not shared_txns.payment_method_exists(db, user_id, payment_method):
            if allow_create_payment_method:
                ensure_payment_method(db, user_id, payment_method)
            else:
                return CreateResult(
                    status=ServiceStatus.PAYMENT_METHOD_NOT_FOUND,
                    missing_payment_method=payment_method,
                    error_message=f"Payment method '{payment_method}' does not exist",
                )

    # 3. Duplicate check
    duplicate = shared_txns.find_duplicate(
        db, user_id, type_, amount, category, parsed_date
    )

    # 4. Insert transaction
    txn = shared_txns.insert_transaction(
        db,
        user_id=user_id,
        type_=type_,
        amount=amount,
        category=category,
        txn_date=parsed_date,
        note=note,
        payment_method=payment_method,
    )

    if duplicate:
        return CreateResult(
            status=ServiceStatus.DUPLICATE_DETECTED,
            transaction=txn,
            is_duplicate=True,
            duplicate_of=duplicate,
        )

    return CreateResult(status=ServiceStatus.CREATED, transaction=txn)


def get_transactions(
    db: Session,
    user_id: int,
    *,
    type_: Optional[str] = None,
    category: Optional[str] = None,
    payment_method: Optional[str] = None,
    date: Optional[dt_date | str] = None,
    date_from: Optional[dt_date | str] = None,
    date_to: Optional[dt_date | str] = None,
    month: Optional[str] = None,
    amount_min: Optional[float] = None,
    amount_max: Optional[float] = None,
    sort_by: Optional[List[str]] = None,
    sort_order: str = "desc",
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    max_candidates: Optional[int] = None,
) -> TransactionListResult:
    """Unified query builder and executor for listing and staging transactions."""
    if date and (date_from or date_to):
        return TransactionListResult(
            status=ServiceStatus.VALIDATION_ERROR,
            error_message="Use either 'date' for exact date or 'date_from'/'date_to' for range, not both.",
        )

    query = select(Transaction).where(Transaction.user_id == user_id)

    if type_:
        query = query.where(Transaction.type == type_)

    if category:
        query = query.where(Transaction.category == category)

    if payment_method:
        query = query.where(Transaction.payment_method == payment_method)

    if date:
        try:
            query = query.where(Transaction.date == _parse_date(date))
        except ValueError as e:
            return TransactionListResult(
                status=ServiceStatus.VALIDATION_ERROR,
                error_message=f"Invalid date: {e}",
            )

    if date_from:
        try:
            query = query.where(Transaction.date >= _parse_date(date_from))
        except ValueError as e:
            return TransactionListResult(
                status=ServiceStatus.VALIDATION_ERROR,
                error_message=f"Invalid date_from: {e}",
            )

    if date_to:
        try:
            query = query.where(Transaction.date <= _parse_date(date_to))
        except ValueError as e:
            return TransactionListResult(
                status=ServiceStatus.VALIDATION_ERROR,
                error_message=f"Invalid date_to: {e}",
            )

    if month and not date and not date_from and not date_to:
        try:
            year, mon = int(month.split("-")[0]), int(month.split("-")[1])
            last_day = monthrange(year, mon)[1]
            query = query.where(Transaction.date >= dt_date(year, mon, 1))
            query = query.where(Transaction.date <= dt_date(year, mon, last_day))
        except (ValueError, IndexError):
            return TransactionListResult(
                status=ServiceStatus.VALIDATION_ERROR,
                error_message="month must be in YYYY-MM format",
            )

    if amount_min is not None:
        query = query.where(Transaction.amount >= amount_min)

    if amount_max is not None:
        query = query.where(Transaction.amount <= amount_max)

    # Sorting
    if not sort_by:
        order_clauses = [Transaction.date.desc(), Transaction.id.desc()] if sort_order == "desc" else [Transaction.date.asc(), Transaction.id.asc()]
    else:
        col_map = {
            "date": Transaction.date,
            "amount": Transaction.amount,
            "id": Transaction.id,
        }
        order_clauses = []
        for s in sort_by:
            col = col_map.get(s, Transaction.date)
            order_clauses.append(col.desc() if sort_order == "desc" else col.asc())

    query = query.order_by(*order_clauses)

    # Safeguard check
    all_results = db.exec(query).all()
    total = len(all_results)

    if max_candidates is not None and total > max_candidates:
        return TransactionListResult(
            status=ServiceStatus.TOO_MANY_CANDIDATES,
            transactions=all_results,
            total_count=total,
            error_message=f"Found {total} matching transactions — exceeds limit of {max_candidates}.",
        )

    # Pagination slice
    if offset:
        all_results = all_results[offset:]
    if limit:
        all_results = all_results[:limit]

    return TransactionListResult(
        status=ServiceStatus.SUCCESS,
        transactions=all_results,
        total_count=total,
    )


def update_transaction(
    db: Session,
    user_id: int,
    txn_id: int,
    *,
    amount: Optional[float] = None,
    type_: Optional[str] = None,
    category: Optional[str] = None,
    date: Optional[dt_date | str] = None,
    note: Optional[str] = None,
    payment_method: Optional[str] = None,
    allow_create_category: bool = False,
    allow_create_payment_method: bool = False,
) -> UpdateResult:
    """Verify ownership and update specified fields of an existing transaction."""
    txn = shared_txns.get_owned_transaction(db, user_id, txn_id)
    if not txn:
        return UpdateResult(
            status=ServiceStatus.NOT_FOUND,
            error_message=f"Transaction {txn_id} not found",
        )

    updates: Dict[str, Any] = {}
    if amount is not None:
        if amount <= 0:
            return UpdateResult(
                status=ServiceStatus.VALIDATION_ERROR,
                error_message="amount must be greater than zero",
            )
        updates["amount"] = float(amount)

    target_type = type_ if type_ is not None else txn.type
    if type_ is not None:
        if type_ not in ("income", "expense"):
            return UpdateResult(
                status=ServiceStatus.VALIDATION_ERROR,
                error_message="type must be 'income' or 'expense'",
            )
        updates["type"] = type_

    if category is not None:
        if not shared_txns.category_exists(db, user_id, category, target_type):
            if allow_create_category:
                ensure_category(db, user_id, category, target_type)
            else:
                return UpdateResult(
                    status=ServiceStatus.CATEGORY_NOT_FOUND,
                    missing_category=category,
                    error_message=f"Category '{category}' does not exist for type '{target_type}'",
                )
        updates["category"] = category

    if payment_method is not None:
        if payment_method and not shared_txns.payment_method_exists(db, user_id, payment_method):
            if allow_create_payment_method:
                ensure_payment_method(db, user_id, payment_method)
            else:
                return UpdateResult(
                    status=ServiceStatus.PAYMENT_METHOD_NOT_FOUND,
                    missing_payment_method=payment_method,
                    error_message=f"Payment method '{payment_method}' does not exist",
                )
        updates["payment_method"] = payment_method

    if date is not None:
        try:
            updates["date"] = _parse_date(date)
        except ValueError as e:
            return UpdateResult(
                status=ServiceStatus.VALIDATION_ERROR,
                error_message=f"Invalid date format: {e}",
            )

    if note is not None:
        updates["note"] = note

    if not updates:
        return UpdateResult(
            status=ServiceStatus.NO_FIELDS_TO_UPDATE,
            error_message="No fields provided to update",
        )

    for field_name, value in updates.items():
        setattr(txn, field_name, value)

    db.add(txn)
    db.commit()
    db.refresh(txn)

    return UpdateResult(
        status=ServiceStatus.SUCCESS,
        transaction=txn,
        updated_fields=updates,
    )


def delete_transaction(db: Session, user_id: int, txn_id: int) -> DeleteResult:
    """Verify ownership and delete a transaction."""
    txn = shared_txns.get_owned_transaction(db, user_id, txn_id)
    if not txn:
        return DeleteResult(
            status=ServiceStatus.NOT_FOUND,
            error_message=f"Transaction {txn_id} not found",
        )

    db.delete(txn)
    db.commit()
    return DeleteResult(status=ServiceStatus.SUCCESS, deleted_id=txn_id)