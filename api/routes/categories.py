"""
FinOS — category routes (api/routes/categories.py)

GET    /categories/      — list all categories for current user (filter by type)
POST   /categories/      — add a custom category
DELETE /categories/{id}  — delete (blocked with 400 if any transaction uses it)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from api.deps import get_current_user, get_db
from api.schemas import CategoryCreate, CategoryRead
from core.models import Category, Transaction, User
from core import shared_txns


router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("/", response_model=list[CategoryRead])
def list_categories(
    type: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = select(Category).where(Category.user_id == current_user.id)
    if type:
        query = query.where(Category.type == type)
    return db.exec(query.order_by(Category.name)).all()


@router.post("/", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(
    body: CategoryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if body.type not in ("income", "expense"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="type must be 'income' or 'expense'",
        )

    if shared_txns.category_exists(db, current_user.id, body.name, body.type):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Category '{body.name}' already exists for type '{body.type}'",
        )

    cat = Category(user_id=current_user.id, name=body.name, type=body.type, is_default=False)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.delete("/{category_id}", status_code=status.HTTP_200_OK)
def delete_category(
    category_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cat = shared_txns.get_owned_category(db, current_user.id, category_id)
    if not cat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    txn_exists = db.exec(
        select(Transaction).where(
            Transaction.user_id == current_user.id,
            Transaction.category == cat.name,
        )
    ).first()

    if txn_exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete '{cat.name}' — transactions exist with this category. Reassign them first.",
        )

    db.delete(cat)
    db.commit()
    return {"detail": f"Category '{cat.name}' deleted"}