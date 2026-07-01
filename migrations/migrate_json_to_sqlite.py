"""
FinOS — one-time JSON → SQLite migration (migrations/migrate_json_to_sqlite.py)

Migrates u001 (Harsh Bhanu) data only.

Sources:
    expense-tracker/data/users.json              → User record
    expense-tracker/data/transactions_u001.json  → Transaction rows
    finance-agent/data/config_u001.json          → monthly_income, currency

Skipped intentionally:
    budgets_u001.json   → month-scoped structure incompatible with FinOS Budget table
                                set budgets fresh in FinOS after migration
    u002 (Demo)         → no real data

Safe to run multiple times — users and transactions are deduplicated.

Usage:
    python migrations/migrate_json_to_sqlite.py \
        --expense-dir ../expense-tracker/data \
        --finance-dir ../finance-agent/data

Run from the finos/ root directory.
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, select

from config import DEFAULT_EXPENSE_CATEGORIES, DEFAULT_INCOME_CATEGORIES
from core.database import create_db, engine
from core.models import Category, Transaction, User

TARGET_UID = "u001"
TARGET_USERNAME = "Harsh Bhanu"


# ── Helpers ────────────────────────────────────────────────────────────────
def parse_date(value: str) -> date:
    """Parse YYYY-MM-DD string to date. Returns today if invalid."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return date.today()


def parse_datetime(value: str) -> datetime:
    """Parse ISO datetime string. Returns utcnow if invalid."""
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return datetime.utcnow()


def seed_default_categories(user_id: int, db: Session) -> None:
    """Insert default income and expense categories for a user."""
    for name in DEFAULT_INCOME_CATEGORIES:
        db.add(Category(user_id=user_id, name=name, type="income", is_default=True))
    for name in DEFAULT_EXPENSE_CATEGORIES:
        db.add(Category(user_id=user_id, name=name, type="expense", is_default=True))
    db.commit()


def get_or_create_category(user_id: int, name: str, type_: str, db: Session) -> bool:
    """
    Insert category if it doesn't already exist for this user.
    Returns True if a new category was created.
    Sets is_default correctly based on the defaults lists.
    """
    existing = db.exec(
        select(Category).where(
            Category.user_id == user_id,
            Category.name == name,
            Category.type == type_,
        )
    ).first()
    if not existing:
        is_default = (
            name in DEFAULT_INCOME_CATEGORIES
            if type_ == "income"
            else name in DEFAULT_EXPENSE_CATEGORIES
        )
        db.add(Category(user_id=user_id, name=name, type=type_, is_default=is_default))
        db.commit()
        return True
    return False


def transaction_exists(
    user_id: int,
    amount: float,
    category: str,
    txn_date: date,
    note: str,
    db: Session,
) -> bool:
    """Returns True if an identical transaction already exists — prevents duplicates on re-run."""
    return db.exec(
        select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.amount == amount,
            Transaction.category == category,
            Transaction.date == txn_date,
            Transaction.note == note,
        )
    ).first() is not None


# ── Main migration ─────────────────────────────────────────────────────────
def migrate(expense_dir: Path, finance_dir: Path) -> None:
    create_db()

    # ── Validate source files exist ──────────────────────────────────────
    users_file = expense_dir / "users.json"
    txn_file = expense_dir / f"transactions_{TARGET_UID}.json"
    config_file = finance_dir / f"config_{TARGET_UID}.json"

    missing = [f for f in [users_file, txn_file, config_file] if not f.exists()]
    if missing:
        for f in missing:
            print(f"[ERROR] File not found: {f}")
        sys.exit(1)

    # ── Load source files ────────────────────────────────────────────────
    with open(users_file) as f:
        users_data = json.load(f)

    with open(txn_file) as f:
        txns_data = json.load(f)

    with open(config_file) as f:
        config_data = json.load(f)

    user_info = users_data.get(TARGET_UID)
    if not user_info:
        print(f"[ERROR] '{TARGET_UID}' not found in users.json")
        sys.exit(1)

    total_txns = 0
    total_categories = 0
    skipped_txns = 0

    with Session(engine) as db:

        # ── Check if already migrated ────────────────────────────────────
        existing_user = db.exec(
            select(User).where(User.username == TARGET_USERNAME)
        ).first()

        if existing_user:
            print(f"  [SKIP] User '{TARGET_USERNAME}' already exists — skipping user + category creation")
            user = existing_user
        else:
            # ── Create user ──────────────────────────────────────────────
            # Password is SHA-256 from expense-tracker, FinOS uses bcrypt.
            # Migrated user will need to reset password on first login,
            # or re-signup via the web UI.
            user = User(
                username=TARGET_USERNAME,
                password_hash=user_info.get("password", ""),
                monthly_income=float(config_data.get("monthly_income", 0.0)),
                currency=config_data.get("currency", "INR"),
                created_at=parse_datetime(user_info.get("created_at", "")),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"  [OK] Created user '{TARGET_USERNAME}' (id={user.id})")

            # ── Seed default categories ──────────────────────────────────
            seed_default_categories(user.id, db)
            print(f"  [OK] Default categories seeded")

            # ── Migrate custom categories ────────────────────────────────
            user_categories = user_info.get("categories", {})
            for cat_name in user_categories.get("income", []):
                if get_or_create_category(user.id, cat_name, "income", db):
                    total_categories += 1
            for cat_name in user_categories.get("expense", []):
                if get_or_create_category(user.id, cat_name, "expense", db):
                    total_categories += 1
            print(f"  [OK] Custom categories added: {total_categories}")

        # ── Migrate transactions ─────────────────────────────────────────
        for _txn_id, txn in txns_data.items():
            amount   = float(txn.get("amount", 0))
            category = txn.get("category", "Other")
            txn_date = parse_date(txn.get("date", ""))
            note     = txn.get("description") or txn.get("note") or ""
            txn_type = txn.get("type", "expense")

            if transaction_exists(user.id, amount, category, txn_date, note, db):
                skipped_txns += 1
                continue

            db.add(Transaction(
                user_id=user.id,
                amount=amount,
                type=txn_type,
                category=category,
                date=txn_date,
                note=note,
            ))
            total_txns += 1

        db.commit()
        print(f"  [OK] Transactions migrated : {total_txns}")
        print(f"  [OK] Transactions skipped  : {skipped_txns} (duplicates)")
        print(f"\n  [NOTE] Budgets skipped intentionally — set them fresh in FinOS")
        print(f"  [NOTE] Password hash is SHA-256 from expense-tracker.")
        print(f"         Log in via FinOS signup to set a bcrypt password.")

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n── Migration complete ──────────────────────────────")
    print(f"  User             : {TARGET_USERNAME}")
    print(f"  Transactions     : {total_txns} migrated, {skipped_txns} skipped")
    print(f"  Categories added : {total_categories}")
    print(f"  DB location      : {engine.url}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Migrate u001 (Harsh Bhanu) data from expense-tracker + finance-agent to FinOS SQLite"
    )
    parser.add_argument(
        "--expense-dir",
        type=Path,
        default=Path("../expense-tracker/data"),
        help="Path to expense-tracker data directory (default: ../expense-tracker/data)",
    )
    parser.add_argument(
        "--finance-dir",
        type=Path,
        default=Path("../finance-agent/data"),
        help="Path to finance-agent data directory (default: ../finance-agent/data)",
    )
    args = parser.parse_args()
    print(f"\n── Starting migration ──────────────────────────────")
    print(f"  expense-tracker : {args.expense_dir}")
    print(f"  finance-agent   : {args.finance_dir}")
    print()
    migrate(args.expense_dir, args.finance_dir)