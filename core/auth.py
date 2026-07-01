"""
FinOS — auth utilities (core/auth.py)

Two responsibilities only:
1. Password hashing — bcrypt directly (passlib has Python 3.12 compat issues)
2. Session token — random hex token stored in Session table

No JWT. No middleware. Simple Bearer token in Authorization header.
Token lookup is done per-request in api/deps.py.
"""

import secrets 
from datetime import datetime, timedelta, timezone, UTC
from typing import Optional

import bcrypt
from sqlmodel import Session, select

from config import TOKEN_EXPIRE_DAYS
from core.models import Session as AuthSession, User


# ── Password hashing ───────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Return bcrypt hash of a plain-text password."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the stored bcrypt hash."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ── Session tokens ─────────────────────────────────────────────────────────

def create_token(user_id: int, db: Session) -> str:
    """
    Generate a secure random token, persist it in the Session table,
    and return the token string to send back to the client.
    """

    token = secrets.token_hex(32)   # 64-char hex string
    auth_session = AuthSession(user_id=user_id, token=token)
    db.add(auth_session)
    db.commit()
    db.refresh(auth_session)
    return token


def get_user_by_token(token: str, db: Session) -> Optional[User]:
    """
    Look up a session token. Returns the User if the token exists and
    has not expired, otherwise returns None.
    """

    auth_session = db.exec(
        select(AuthSession).where(AuthSession.token == token)
    ).first()

    if not auth_session:
        return None

    # Check expiry — compare naive datetimes consistently
    expiry = auth_session.created_at + timedelta(days=TOKEN_EXPIRE_DAYS)
    if datetime.now(UTC) > expiry.replace(tzinfo=UTC):
        db.delete(auth_session)
        db.commit()
        return None

    return db.get(User, auth_session.user_id)


def delete_token(token: str, db: Session) -> bool:
    """
    Invalidate a session token (logout).
    Returns True if the token existed and was deleted, False otherwise.
    """

    auth_session = db.exec(
        select(AuthSession).where(AuthSession.token == token)
    ).first()

    if not auth_session:
        return False

    db.delete(auth_session)
    db.commit()
    return True
