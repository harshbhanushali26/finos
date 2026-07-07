"""
FinOS — database models (core/models.py)

Five SQLModel tables. Design decisions:
- Transaction.category is a plain string (not FK) — matches expense-tracker behavior.
    Deleting a category does NOT break old transactions; they keep the string.
- Category deletion is blocked at the API layer (returns 400) if transactions exist.
- DependencyState is NOT a table — in-memory only (agent session).
- No Alembic in v1 — create_all() runs on startup.
- Budget includes created_at for audit trail.
"""

from datetime import datetime, date, UTC
from typing import Optional

from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    monthly_income: float = Field(default=0.0)
    currency: str = Field(default="INR")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Category(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    name: str = Field(index=True)
    type: str                                                   # "income" or "expense"
    is_default: bool = Field(default=False)                     # True = seeded at signup for defaults(not by users)


class PaymentMethod(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    name: str = Field(index=True)
    is_default: bool = Field(default=False)


class Transaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    amount: float
    type: str
    category: str                                               # stored as string — no FK by design
    payment_method: str | None = Field(default=None)
    date: date
    note: str = Field(default="")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Budget(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    category: str
    monthly_limit: float
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Session(SQLModel, table=True):
    """Auth session — maps a random token to a user_id."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    token: str = Field(unique=True, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: Optional[datetime] = Field(default=None)