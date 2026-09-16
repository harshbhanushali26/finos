"""
FinOS — transaction routes (api/routes/transactions.py)

Thin HTTP adapter over core/services.py:
POST   /transactions/      — add a transaction
GET    /transactions/       — list with filters
PUT    /transactions/{id}   — update (only provided fields)
DELETE /transactions/{id}   — delete (ownership verified)
"""

from datetime import date as dt_date
from enum import Enum
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from api.deps import get_current_user, get_db
from api.schemas import TransactionCreate, TransactionRead, TransactionUpdate
from core.models import User
from core.services import (
    ServiceStatus,
    create_transaction as service_create_transaction,
    get_transactions as service_get_transactions,
    update_transaction as service_update_transaction,
    delete_transaction as service_delete_transaction,
)


router = APIRouter(prefix="/transactions", tags=["transactions"])


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


class SortBy(str, Enum):
    date = "date"
    amount = "amount"


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/", response_model=TransactionRead, status_code=status.HTTP_201_CREATED)
def add_transaction(
    body: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a transaction using core.services."""
    result = service_create_transaction(
        db=db,
        user_id=current_user.id,
        type_=body.type,
        amount=body.amount,
        category=body.category,
        date=body.date,
        note=body.note or "",
        payment_method=body.payment_method,
        allow_create_category=False,
        allow_create_payment_method=False,
    )

    if result.status == ServiceStatus.VALIDATION_ERROR:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result.error_message,
        )

    if result.status == ServiceStatus.CATEGORY_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Category '{body.category}' does not exist for type '{body.type}'. Add it from the Manage page first.",
        )

    if result.status == ServiceStatus.PAYMENT_METHOD_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment method '{body.payment_method}' does not exist. Add it from the Manage page first.",
        )

    response = TransactionRead(**result.transaction.model_dump())
    if result.is_duplicate:
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
    """List and filter transactions using core.services."""
    sort_fields = [s.value for s in sort_by]

    result = service_get_transactions(
        db=db,
        user_id=current_user.id,
        type_=type,
        category=category,
        payment_method=payment_method,
        date=date,
        date_from=date_from,
        date_to=date_to,
        month=month,
        amount_min=amount_min,
        amount_max=amount_max,
        sort_by=sort_fields,
        sort_order=sort_order.value,
        limit=limit,
        offset=offset,
    )

    if result.status == ServiceStatus.VALIDATION_ERROR:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result.error_message,
        )

    return result.transactions


@router.put("/{transaction_id}", response_model=TransactionRead)
def update_transaction(
    transaction_id: int,
    body: TransactionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a transaction using core.services."""
    result = service_update_transaction(
        db=db,
        user_id=current_user.id,
        txn_id=transaction_id,
        amount=body.amount,
        type_=body.type,
        category=body.category,
        date=body.date,
        note=body.note,
        payment_method=body.payment_method,
        allow_create_category=False,
        allow_create_payment_method=False,
    )

    if result.status == ServiceStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found",
        )

    if result.status == ServiceStatus.CATEGORY_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Category '{result.missing_category}' does not exist. Add it from the Manage page first.",
        )

    if result.status == ServiceStatus.PAYMENT_METHOD_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment method '{result.missing_payment_method}' does not exist. Add it from the Manage page first.",
        )

    if result.status == ServiceStatus.VALIDATION_ERROR:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result.error_message,
        )

    return result.transaction


@router.delete("/{transaction_id}", status_code=status.HTTP_200_OK)
def delete_transaction(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a transaction using core.services."""
    result = service_delete_transaction(
        db=db,
        user_id=current_user.id,
        txn_id=transaction_id,
    )

    if result.status == ServiceStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found",
        )

    return {"detail": f"Transaction {transaction_id} deleted"}