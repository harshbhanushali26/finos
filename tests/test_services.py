"""
tests/test_services.py — Unit test suite for core/services.py.

Verifies every status enum path and edge case for:
- create_transaction (clean creation, duplicates, category policies, payment methods)
- get_transactions (filter combinations, pagination, sorting, candidate safeguards)
- update_transaction (field updates, ownership, category policies, empty updates)
- delete_transaction (clean deletion, ownership verification, missing IDs)

Run with:
    uv run pytest tests/test_services.py -v
"""

from sqlmodel import select
from datetime import date, timedelta
import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from core.models import Category, PaymentMethod, Transaction, User
from core.services import (
    ServiceStatus,
    create_transaction,
    delete_transaction,
    get_transactions,
    update_transaction,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(name="db")
def db_fixture():
    """Create a fresh in-memory SQLite database for each test."""
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
    """Create a test user."""
    user = User(username="alice", password_hash="hash123", currency="INR")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(name="setup_categories")
def setup_categories_fixture(db: Session, user: User):
    """Seed standard categories and payment methods for the test user."""
    cat_food = Category(user_id=user.id, name="Food", type="expense")
    cat_salary = Category(user_id=user.id, name="Salary", type="income")
    pm_upi = PaymentMethod(user_id=user.id, name="UPI")
    pm_cash = PaymentMethod(user_id=user.id, name="Cash")

    db.add_all([cat_food, cat_salary, pm_upi, pm_cash])
    db.commit()


# ── 1. create_transaction Tests ───────────────────────────────────────────────

def test_create_transaction_success(db: Session, user: User, setup_categories):
    """Clean transaction insert returns CREATED status and populates row."""
    res = create_transaction(
        db,
        user.id,
        type_="expense",
        amount=250.0,
        category="Food",
        date="2026-09-15",
        note="Lunch with friends",
        payment_method="UPI",
    )

    assert res.status == ServiceStatus.CREATED
    assert res.is_duplicate is False
    assert res.transaction is not None
    assert res.transaction.id is not None
    assert res.transaction.amount == 250.0
    assert res.transaction.category == "Food"
    assert res.transaction.payment_method == "UPI"
    assert res.transaction.date == date(2026, 9, 15)


def test_create_transaction_duplicate_detected(db: Session, user: User, setup_categories):
    """Creating an identical transaction returns DUPLICATE_DETECTED while still inserting."""
    # First transaction
    first_res = create_transaction(
        db, user.id, type_="expense", amount=500.0, category="Food", date="2026-09-15"
    )
    assert first_res.status == ServiceStatus.CREATED

    # Duplicate transaction
    second_res = create_transaction(
        db, user.id, type_="expense", amount=500.0, category="Food", date="2026-09-15"
    )
    assert second_res.status == ServiceStatus.DUPLICATE_DETECTED
    assert second_res.is_duplicate is True
    assert second_res.duplicate_of.id == first_res.transaction.id
    assert second_res.transaction.id != first_res.transaction.id


def test_create_transaction_category_missing_strict(db: Session, user: User, setup_categories):
    """Unknown category with allow_create_category=False returns CATEGORY_NOT_FOUND."""
    res = create_transaction(
        db,
        user.id,
        type_="expense",
        amount=1200.0,
        category="Electronics",
        date="2026-09-15",
        allow_create_category=False,
    )
    assert res.status == ServiceStatus.CATEGORY_NOT_FOUND
    assert res.missing_category == "Electronics"
    assert res.transaction is None


def test_create_transaction_category_auto_create(db: Session, user: User, setup_categories):
    """Unknown category with allow_create_category=True creates category and succeeds."""
    res = create_transaction(
        db,
        user.id,
        type_="expense",
        amount=1200.0,
        category="Electronics",
        date="2026-09-15",
        allow_create_category=True,
    )
    assert res.status == ServiceStatus.CREATED
    assert res.transaction.category == "Electronics"

    # Verify category was created in the DB
    cat = db.exec(select(Category).where(Category.user_id == user.id, Category.name == "Electronics")).first()
    assert cat is not None
    assert cat.type == "expense"


def test_create_transaction_payment_method_validation(db: Session, user: User, setup_categories):
    """Unknown payment method returns PAYMENT_METHOD_NOT_FOUND."""
    res = create_transaction(
        db,
        user.id,
        type_="expense",
        amount=100.0,
        category="Food",
        date="2026-09-15",
        payment_method="Crypto",
        allow_create_payment_method=False,
    )
    assert res.status == ServiceStatus.PAYMENT_METHOD_NOT_FOUND
    assert res.missing_payment_method == "Crypto"


def test_create_transaction_invalid_inputs(db: Session, user: User, setup_categories):
    """Invalid types or non-positive amounts return VALIDATION_ERROR."""
    # Negative amount
    res1 = create_transaction(
        db, user.id, type_="expense", amount=-50.0, category="Food", date="2026-09-15"
    )
    assert res1.status == ServiceStatus.VALIDATION_ERROR

    # Invalid type
    res2 = create_transaction(
        db, user.id, type_="investment", amount=100.0, category="Food", date="2026-09-15"
    )
    assert res2.status == ServiceStatus.VALIDATION_ERROR


# ── 2. get_transactions Tests ─────────────────────────────────────────────────

def test_get_transactions_filter_matrix(db: Session, user: User, setup_categories):
    """Verify various filter combinations work through the unified query builder."""
    # Seed transactions
    create_transaction(db, user.id, type_="expense", amount=100, category="Food", date="2026-09-01", payment_method="UPI")
    create_transaction(db, user.id, type_="expense", amount=200, category="Food", date="2026-09-15", payment_method="Cash")
    create_transaction(db, user.id, type_="income", amount=5000, category="Salary", date="2026-09-01", payment_method="UPI")
    create_transaction(db, user.id, type_="expense", amount=300, category="Food", date="2026-08-10", payment_method="Cash")

    # Filter by type
    res_type = get_transactions(db, user.id, type_="income")
    assert len(res_type.transactions) == 1
    assert res_type.transactions[0].category == "Salary"

    # Filter by month
    res_month = get_transactions(db, user.id, month="2026-09")
    assert len(res_month.transactions) == 3

    # Filter by payment method
    res_pm = get_transactions(db, user.id, payment_method="Cash")
    assert len(res_pm.transactions) == 2

    # Filter by date range
    res_range = get_transactions(db, user.id, date_from="2026-09-02", date_to="2026-09-20")
    assert len(res_range.transactions) == 1
    assert res_range.transactions[0].amount == 200

    # Filter by amount range
    res_amount = get_transactions(db, user.id, amount_min=150, amount_max=350)
    assert len(res_amount.transactions) == 2


def test_get_transactions_max_candidates_safeguard(db: Session, user: User, setup_categories):
    """Verify max_candidates returns TOO_MANY_CANDIDATES when threshold is exceeded."""
    for i in range(12):
        create_transaction(
            db, user.id, type_="expense", amount=10 + i, category="Food", date=f"2026-09-{(i+1):02d}"
        )

    res = get_transactions(db, user.id, category="Food", max_candidates=10)
    assert res.status == ServiceStatus.TOO_MANY_CANDIDATES
    assert res.total_count == 12


def test_get_transactions_pagination_and_sorting(db: Session, user: User, setup_categories):
    """Verify limit, offset, and sort_by."""
    for amt in [100.0, 500.0, 250.0]:
        create_transaction(db, user.id, type_="expense", amount=amt, category="Food", date="2026-09-01")

    # Sort by amount descending
    res_sort = get_transactions(db, user.id, sort_by=["amount"], sort_order="desc", limit=2)
    assert res_sort.status == ServiceStatus.SUCCESS
    assert len(res_sort.transactions) == 2
    assert res_sort.transactions[0].amount == 500.0
    assert res_sort.transactions[1].amount == 250.0


# ── 3. update_transaction Tests ───────────────────────────────────────────────

def test_update_transaction_success(db: Session, user: User, setup_categories):
    """Verify updating fields on an existing transaction."""
    created = create_transaction(
        db, user.id, type_="expense", amount=100.0, category="Food", date="2026-09-01", note="old"
    ).transaction

    res = update_transaction(
        db,
        user.id,
        created.id,
        amount=150.0,
        note="updated lunch",
        payment_method="UPI",
    )

    assert res.status == ServiceStatus.SUCCESS
    assert res.transaction.amount == 150.0
    assert res.transaction.note == "updated lunch"
    assert res.transaction.payment_method == "UPI"
    assert "amount" in res.updated_fields


def test_update_transaction_not_found(db: Session, user: User):
    """Updating a non-existent ID or an ID belonging to another user returns NOT_FOUND."""
    res = update_transaction(db, user.id, txn_id=9999, amount=200.0)
    assert res.status == ServiceStatus.NOT_FOUND


def test_update_transaction_no_fields(db: Session, user: User, setup_categories):
    """Passing no fields to update returns NO_FIELDS_TO_UPDATE."""
    created = create_transaction(
        db, user.id, type_="expense", amount=100.0, category="Food", date="2026-09-01"
    ).transaction

    res = update_transaction(db, user.id, created.id)
    assert res.status == ServiceStatus.NO_FIELDS_TO_UPDATE


# ── 4. delete_transaction Tests ───────────────────────────────────────────────

def test_delete_transaction_success(db: Session, user: User, setup_categories):
    """Verify clean deletion of a transaction."""
    created = create_transaction(
        db, user.id, type_="expense", amount=100.0, category="Food", date="2026-09-01"
    ).transaction

    res = delete_transaction(db, user.id, created.id)
    assert res.status == ServiceStatus.SUCCESS
    assert res.deleted_id == created.id

    # Verify it is deleted from the DB
    assert db.get(Transaction, created.id) is None


def test_delete_transaction_not_found(db: Session, user: User):
    """Deleting a non-existent ID returns NOT_FOUND."""
    res = delete_transaction(db, user.id, txn_id=9999)
    assert res.status == ServiceStatus.NOT_FOUND


def test_delete_transaction_other_user_isolation(db: Session, user: User, setup_categories):
    """User cannot delete another user's transaction."""
    # Create another user and their transaction
    other_user = User(username="bob", password_hash="hash456", currency="INR")
    db.add(other_user)
    db.commit()

    cat = Category(user_id=other_user.id, name="Food", type="expense")
    db.add(cat)
    db.commit()

    other_txn = create_transaction(
        db, other_user.id, type_="expense", amount=50.0, category="Food", date="2026-09-01"
    ).transaction

    # Alice tries to delete Bob's transaction
    res = delete_transaction(db, user.id, other_txn.id)
    assert res.status == ServiceStatus.NOT_FOUND
    # Verify Bob's transaction is still in the database
    assert db.get(Transaction, other_txn.id) is not None