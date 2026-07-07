"""
FinOS — transaction routes (api/routes/transactions.py)

POST   /transactions/      — add a transaction
GET    /transactions/       — list with filters
PUT    /transactions/{id}   — update (only provided fields)
DELETE /transactions/{id}   — delete (ownership verified)
"""

from datetime import date as dt_date
from enum import Enum
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlmodel import Session, select

from api.deps import get_current_user, get_db
from api.schemas import TransactionCreate, TransactionRead, TransactionUpdate
from core.models import Transaction, User
from core import shared_txns


router = APIRouter(prefix="/transactions", tags=["transactions"])


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


class SortBy(str, Enum):
    date = "date"
    amount = "amount"


def _validate_category_exists(user_id: int, name: str, type_: str, db: Session) -> None:
    """Reject if category doesn't already exist. Categories are dropdown-only —
    created via the Manage page, never auto-created on transaction submit."""
    if not shared_txns.category_exists(db, user_id, name, type_):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Category '{name}' does not exist for type '{type_}'. Add it from the Manage page first.",
        )


def _validate_payment_method_exists(user_id: int, name: str, db: Session) -> None:
    """Reject if payment method doesn't already exist. Same dropdown-only rule as categories."""
    if not shared_txns.payment_method_exists(db, user_id, name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment method '{name}' does not exist. Add it from the Manage page first.",
        )


@router.post("/", response_model=TransactionRead, status_code=status.HTTP_201_CREATED)
def add_transaction(
    body: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    if body.type not in ("income", "expense"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="type must be 'income' or 'expense'",
        )

    _validate_category_exists(current_user.id, body.category, body.type, db)

    if body.payment_method:
        _validate_payment_method_exists(current_user.id, body.payment_method, db)

    # NEW (point 1a): form/API path now gets the same duplicate check chat already had.
    duplicate = shared_txns.find_duplicate(
        db, current_user.id, body.type, body.amount, body.category, body.date
    )

    txn = shared_txns.insert_transaction(
        db, current_user.id, body.type, body.amount, body.category, body.date,
        note=body.note or "", payment_method=body.payment_method,
    )

    response = TransactionRead(**txn.model_dump())
    if duplicate:
        # requires TransactionRead to have: duplicate_warning: str | None = None
        response.duplicate_warning = (
            f"Possible duplicate — a {body.type} of {body.amount:,.0f} for "
            f"{body.category} on {body.date} already existed before this entry."
        )
    return response


@router.get("/", response_model=list[TransactionRead])
def list_transactions(
    type: Optional[str] = None,
    category: Optional[str] = None,
    payment_method: Optional[str] = None,
    date: Optional[dt_date] = None,
    date_from: Optional[dt_date] = None,
    date_to: Optional[dt_date] = None,
    month: Optional[str] = None,
    amount_min: Optional[float] = None,
    amount_max: Optional[float] = None,
    sort_by: list[SortBy] = Query(default=[SortBy.date]),
    sort_order: SortOrder = SortOrder.desc,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    if date and (date_from or date_to):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Use either 'date' for exact date or 'date_from'/'date_to' for range, not both.",
        )

    query = select(Transaction).where(Transaction.user_id == current_user.id)

    if type:
        query = query.where(Transaction.type == type)

    if category:
        query = query.where(Transaction.category == category)

    if payment_method:
        query = query.where(Transaction.payment_method == payment_method)

    if date:
        query = query.where(Transaction.date == date)

    if date_from:
        query = query.where(Transaction.date >= date_from)

    if date_to:
        query = query.where(Transaction.date <= date_to)

    if month and not date and not date_from and not date_to:
        try:
            year, mon = int(month.split("-")[0]), int(month.split("-")[1])
            from calendar import monthrange
            last_day = monthrange(year, mon)[1]
            query = query.where(Transaction.date >= dt_date(year, mon, 1))
            query = query.where(Transaction.date <= dt_date(year, mon, last_day))
        except (ValueError, IndexError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="month must be in YYYY-MM format",
            )

    if amount_min is not None:
        query = query.where(Transaction.amount >= amount_min)

    if amount_max is not None:
        query = query.where(Transaction.amount <= amount_max)

    column_map = {
        SortBy.date: Transaction.date,
        SortBy.amount: Transaction.amount,
    }
    order_clauses = [
        col.asc() if sort_order == SortOrder.asc else col.desc()
        for col in (column_map[s] for s in sort_by)
    ]
    query = query.order_by(*order_clauses).offset(offset).limit(limit)

    return db.exec(query).all()


@router.put("/{transaction_id}", response_model=TransactionRead)
def update_transaction(
    transaction_id: int,
    body: TransactionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    txn = shared_txns.get_owned_transaction(db, current_user.id, transaction_id)
    if not txn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(txn, field, value)

    if "category" in update_data:
        _validate_category_exists(current_user.id, txn.category, txn.type, db)

    if "payment_method" in update_data:
        _validate_payment_method_exists(current_user.id, txn.payment_method, db)

    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


@router.delete("/{transaction_id}", status_code=status.HTTP_200_OK)
def delete_transaction(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    txn = shared_txns.get_owned_transaction(db, current_user.id, transaction_id)
    if not txn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    db.delete(txn)
    db.commit()
    return {"detail": f"Transaction {transaction_id} deleted"}