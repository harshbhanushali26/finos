"""Settings tools — handler functions for user config and preferences.

Reads and writes the User table directly — no config JSON file in FinOS.
monthly_income and currency are stored on the User row.
Preferences (date_format, alerts) are not persisted in v1 — static defaults returned.
"""

from sqlmodel import select
from core.models import User


def get_config(args: dict, session) -> str:
    """Handle get_config tool call — return user settings from User table."""
    try:
        db = session.db_session
        user = db.get(User, session.user_id)

        if not user:
            return "User not found"

        return (
            f"Config for {user.username} — "
            f"Monthly income: ₹{user.monthly_income:,.0f}, "
            f"Currency: {user.currency}, "
            f"Budget warning at: 80%, "
            f"Low balance alert: ₹1,000, "
            f"Date format: DD-MM-YYYY"
        )

    except Exception as e:
        return f"Error getting config: {str(e)}"


def set_monthly_income(args: dict, session) -> str:
    """Handle set_monthly_income tool call — update User.monthly_income."""
    try:
        db = session.db_session
        user = db.get(User, session.user_id)

        if not user:
            return "User not found"

        user.monthly_income = float(args["amount"])
        db.add(user)
        db.commit()

        return f"Monthly income updated to ₹{user.monthly_income:,.0f}"

    except Exception as e:
        return f"Error setting monthly income: {str(e)}"


def set_preference(args: dict, session) -> str:
    """Handle set_preference tool call.

    Preferences beyond monthly_income and currency are not persisted in v1.
    Returns a clear message so the LLM doesn't hallucinate a save.
    """
    key = args.get("key", "")
    value = args.get("value", "")
    return (
        f"Preference '{key}' noted for this session, but preference persistence "
        f"is not available in FinOS v1. Use the Settings page to update your profile."
    )