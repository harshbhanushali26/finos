"""
FinOS — API schemas (api/schemas.py)

Pydantic models for request bodies and responses.
Kept separate from SQLModel table definitions in core/models.py.

Rule: SQLModel tables define what the DB stores.
        These schemas define what the API accepts and returns.
"""

from datetime import datetime, date as dt_date
from typing import Optional
from pydantic import BaseModel


# ── Auth ───────────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class TokenResponse(BaseModel):
    token: str
    username: str
    user_id: int


class UserResponse(BaseModel):
    id: int
    username: str
    monthly_income: float
    currency: str
    created_at: datetime

# ── Categories ─────────────────────────────────────────────────────────────

class CategoryCreate(BaseModel):
    name: str
    type: str   # "income" or "expense"


class CategoryRead(BaseModel):
    id: int
    name: str
    type: str
    is_default: bool

# ── Transactions ───────────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    amount: float
    type: str           # "income" or "expense"
    category: str
    date: dt_date
    note: Optional[str] = ""


class TransactionUpdate(BaseModel):
    amount: Optional[float] = None
    type: Optional[str] = None
    category: Optional[str] = None
    date: Optional[dt_date] = None
    note: Optional[str] = None


class TransactionRead(BaseModel):
    id: int
    amount: float
    type: str
    category: str
    date: dt_date
    note: str
    created_at: datetime


# ── Analytics ──────────────────────────────────────────────────────────────

class SummaryResponse(BaseModel):
    income: float
    expense: float
    balance: float
    period: str


class BreakdownItem(BaseModel):
    category: str
    total: float


class ChartPoint(BaseModel):
    label: str
    income: float
    expense: float


# ── Budget ─────────────────────────────────────────────────────────────────

class BudgetSet(BaseModel):
    category: str
    monthly_limit: float


class BudgetStatusItem(BaseModel):
    category: str
    monthly_limit: float
    spent: float
    remaining: float
    percent_used: float



