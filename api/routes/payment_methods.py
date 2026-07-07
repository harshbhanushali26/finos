"""
FinOS — payment-methods routes (api/routes/payment_methods.py)

GET    /payment-methods/      — list all payment-methods for current user 
POST   /payment-methods/      — add a custom payment-methods
DELETE /payment-methods/{id}  — delete (blocked with 400 if any transaction uses it)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from api.deps import get_current_user, get_db
from api.schemas import PaymentMethodCreate, PaymentMethodRead
from core.models import Transaction, User, PaymentMethod


router = APIRouter(prefix="/payment-methods", tags=["payment-methods"])


@router.get("/", response_model=list[PaymentMethodRead])
def list_payment_methods(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    query = select(PaymentMethod).where(PaymentMethod.user_id == current_user.id)
    return db.exec(query.order_by(PaymentMethod.name)).all()


@router.post("/", response_model=PaymentMethodRead, status_code=status.HTTP_201_CREATED)
def create_payment_methods(
    body: PaymentMethodCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    existing = db.exec(
        select(PaymentMethod).where(
            PaymentMethod.user_id == current_user.id,
            PaymentMethod.name == body.name,
        )
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Payment Method '{body.name}' already exists",
        )

    payment = PaymentMethod(user_id=current_user.id, name=body.name, is_default=False)
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


@router.delete("/{payment_method_id}", status_code=status.HTTP_200_OK)
def delete_payment_method(
    payment_method_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    payment = db.get(PaymentMethod, payment_method_id)
    if not payment or payment.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment Method not found")

    # Block deletion if any transaction references this Payment Method name
    txn_exists = db.exec(
        select(Transaction).where(
            Transaction.user_id == current_user.id,
            Transaction.payment_method == payment.name,
        )
    ).first()

    if txn_exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete '{payment.name}' — transactions exist with this Payment Method. Reassign them first.",
        )

    db.delete(payment)
    db.commit()
    return {"detail": f"Payment Method '{payment.name}' deleted"}