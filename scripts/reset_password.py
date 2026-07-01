"""
FinOS — CLI password reset (scripts/reset_password.py)

Dev/admin-only tool. No UI, no email — directly updates a user's
password hash in the database. Use when a user is locked out.

Usage:
    uv run python scripts/reset_password.py <username> <new_password>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select

from core.auth import hash_password
from core.database import engine
from core.models import User


def reset_password(username: str, new_password: str) -> None:
    if len(new_password) < 8:
        print("Error: new password must be at least 8 characters")
        sys.exit(1)

    with Session(engine) as db:
        user = db.exec(select(User).where(User.username == username)).first()
        if not user:
            print(f"Error: no user found with username '{username}'")
            sys.exit(1)

        user.password_hash = hash_password(new_password)
        db.add(user)
        db.commit()

    print(f"Password reset for user '{username}'.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: uv run python scripts/reset_password.py <username> <new_password>")
        sys.exit(1)

    reset_password(sys.argv[1], sys.argv[2])