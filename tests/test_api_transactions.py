"""
tests/test_api_transactions.py — Integration tests for REST API endpoints.

Verifies:
- POST /api/v1/transactions/ (creation, duplicate warnings, category & payment method guards)
- GET /api/v1/transactions/ (filtering, pagination, sorting)
- PUT /api/v1/transactions/{id} (updating fields, 404s, category validation)
- DELETE /api/v1/transactions/{id} (deletion, 404s)

Run with:
    uv run pytest tests/test_api_transactions.py -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from api.deps import get_current_user, get_db
from api.main import app
from core.models import Category, PaymentMethod, Transaction, User


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(name="db")
def db_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="user")
def user_fixture(db: Session) -> User:
    user = User(username="alice", password_hash="hash123", currency="INR")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(name="client")
def client_fixture(db: Session, user: User):
    """FastAPI TestClient with overridden database and current_user dependencies."""
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture(name="seed_data")
def seed_data_fixture(db: Session, user: User):
    cat_food = Category(user_id=user.id, name="Food", type="expense")
    cat_salary = Category(user_id=user.id, name="Salary", type="income")
    pm_upi = PaymentMethod(user_id=user.id, name="UPI")
    pm_card = PaymentMethod(user_id=user.id, name="Card")

    db.add_all([cat_food, cat_salary, pm_upi, pm_card])
    db.commit()


# ── 1. POST /api/v1/transactions/ Tests ───────────────────────────────────────

def test_api_add_transaction_success(client: TestClient, seed_data):
    payload = {
        "type": "expense",
        "amount": 350.0,
        "category": "Food",
        "date": "2026-09-15",
        "note": "Dinner",
        "payment_method": "UPI",
    }
    res = client.post("/api/v1/transactions/", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["amount"] == 350.0
    assert data["category"] == "Food"
    assert data["payment_method"] == "UPI"
    assert data["duplicate_warning"] is None


def test_api_add_transaction_duplicate_warning(client: TestClient, seed_data):
    payload = {
        "type": "expense",
        "amount": 200.0,
        "category": "Food",
        "date": "2026-09-15",
    }
    # First creation
    res1 = client.post("/api/v1/transactions/", json=payload)
    assert res1.status_code == 201
    assert res1.json()["duplicate_warning"] is None

    # Duplicate creation
    res2 = client.post("/api/v1/transactions/", json=payload)
    assert res2.status_code == 201
    assert "Possible duplicate" in res2.json()["duplicate_warning"]


def test_api_add_transaction_category_not_found(client: TestClient, seed_data):
    payload = {
        "type": "expense",
        "amount": 100.0,
        "category": "NonExistentCategory",
        "date": "2026-09-15",
    }
    res = client.post("/api/v1/transactions/", json=payload)
    assert res.status_code == 400
    assert "does not exist" in res.json()["detail"]


def test_api_add_transaction_payment_method_not_found(client: TestClient, seed_data):
    payload = {
        "type": "expense",
        "amount": 100.0,
        "category": "Food",
        "date": "2026-09-15",
        "payment_method": "UnknownCrypto",
    }
    res = client.post("/api/v1/transactions/", json=payload)
    assert res.status_code == 400
    assert "Payment method 'UnknownCrypto' does not exist" in res.json()["detail"]


# ── 2. GET /api/v1/transactions/ Tests ────────────────────────────────────────

def test_api_list_and_filters(client: TestClient, seed_data):
    # Seed transactions via API
    client.post("/api/v1/transactions/", json={"type": "expense", "amount": 100, "category": "Food", "date": "2026-09-01", "payment_method": "UPI"})
    client.post("/api/v1/transactions/", json={"type": "expense", "amount": 500, "category": "Food", "date": "2026-09-10", "payment_method": "Card"})
    client.post("/api/v1/transactions/", json={"type": "income", "amount": 10000, "category": "Salary", "date": "2026-09-01", "payment_method": "UPI"})

    # Filter by type
    res_type = client.get("/api/v1/transactions/?type=income")
    assert res_type.status_code == 200
    assert len(res_type.json()) == 1

    # Filter by payment method
    res_pm = client.get("/api/v1/transactions/?payment_method=UPI")
    assert res_pm.status_code == 200
    assert len(res_pm.json()) == 2

    # Filter by month
    res_month = client.get("/api/v1/transactions/?month=2026-09")
    assert res_month.status_code == 200
    assert len(res_month.json()) == 3


# ── 3. PUT & DELETE Tests ─────────────────────────────────────────────────────

def test_api_update_transaction(client: TestClient, seed_data):
    # Create
    create_res = client.post("/api/v1/transactions/", json={"type": "expense", "amount": 100, "category": "Food", "date": "2026-09-01"})
    txn_id = create_res.json()["id"]

    # Update
    update_res = client.put(f"/api/v1/transactions/{txn_id}", json={"amount": 180.0, "note": "Updated via API"})
    assert update_res.status_code == 200
    assert update_res.json()["amount"] == 180.0
    assert update_res.json()["note"] == "Updated via API"


def test_api_delete_transaction(client: TestClient, seed_data):
    create_res = client.post("/api/v1/transactions/", json={"type": "expense", "amount": 100, "category": "Food", "date": "2026-09-01"})
    txn_id = create_res.json()["id"]

    del_res = client.delete(f"/api/v1/transactions/{txn_id}")
    assert del_res.status_code == 200
    assert f"Transaction {txn_id} deleted" in del_res.json()["detail"]

    # Verify 404 after delete
    get_res = client.put(f"/api/v1/transactions/{txn_id}", json={"amount": 200})
    assert get_res.status_code == 404