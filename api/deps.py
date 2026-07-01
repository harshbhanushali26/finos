"""
FinOS — shared FastAPI dependencies (api/deps.py)

Two dependencies used across all protected routes:
- get_db()           → yields a database session
- get_current_user() → resolves Bearer token to a User, raises 401 if invalid
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from core.auth import get_user_by_token
from core.database import get_session
from core.models import User


# HTTPBearer extracts the token from "Authorization: Bearer <token>" header

_bearer = HTTPBearer()


def get_db(session: Session = Depends(get_session)) -> Session:
    """Thin wrapper so routes import from api.deps, not core.database."""
    return session


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db)
) -> User:
    """
    Resolve the Bearer token from the Authorization header to a User.
    Raises 401 if the token is missing, invalid, or expired.
    """

    user = get_user_by_token(credentials.credentials, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user

