"""
FinOS — auth routes (api/routes/auth.py)

POST /auth/signup  — create account, return token
POST /auth/login   — verify password, return token
GET  /auth/me      — return current user info
POST /auth/logout  — invalidate token
"""

import re
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from api.deps import get_current_user, get_db
from api.schemas import LoginRequest, SignupRequest, TokenResponse, UserResponse, ChangePasswordRequest
from config import DEFAULT_EXPENSE_CATEGORIES, DEFAULT_INCOME_CATEGORIES
from core.auth import create_token, delete_token, hash_password, verify_password
from core.models import Category, User

router = APIRouter(prefix="/auth", tags=["auth"])
USERNAME_RE = re.compile(r'^[a-zA-Z0-9_-]{5,30}$')


def _seed_default_categories(user_id: int, db: Session) -> None:
    """Insert default income and expense categories for a new user."""

    for name in DEFAULT_INCOME_CATEGORIES:
        db.add(Category(user_id=user_id, name=name, type="income", is_default=True))

    for name in DEFAULT_EXPENSE_CATEGORIES:
        db.add(Category(user_id=user_id, name=name, type="expense", is_default=True))

    db.commit()


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    # Check username is not already taken

    existing = db.exec(select(User).where(User.username ==  body.username)).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{body.username}' is already taken",
        )

    if not USERNAME_RE.match(body.username):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Username must be 5–30 characters, using only letters, numbers, underscores, and hyphens",
        )

    if len(body.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 8 characters",
        )

    # Create User
    user = User(username=body.username, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    # Seed default categories
    _seed_default_categories(user.id, db)

    # Create and return session token
    token = create_token(user.id, db)
    return TokenResponse(token=token, username=user.username, user_id=user.id)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):

    user = db.exec(select(User).where(User.username == body.username)).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = create_token(user.id, db)
    return TokenResponse(token=token, username=user.username, user_id=user.id)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me/password", status_code=status.HTTP_200_OK)
def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )

    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="New password must be at least 8 characters",
        )

    current_user.password_hash = hash_password(body.new_password)
    db.add(current_user)
    db.commit()
    return {"detail": "Password updated successfully"}


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
    ):

    # We need the raw token here — re-read from header via a workaround
    # get_current_user already validated it; we delete by user_id instead

    from sqlmodel import select as sq_select
    from core.models import Session as AuthSession

    sessions = db.exec(
        sq_select(AuthSession).where(AuthSession.user_id == current_user.id)
    ).all()

    for s in sessions:
        db.delete(s)
    db.commit()

    return {"detail": "Logged out successfully"}



