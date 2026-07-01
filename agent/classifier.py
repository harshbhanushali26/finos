"""Classifier
Classifies user intent before LLM call so only relevant tool schemas are sent.

Returns one of: delete, settings, update, add, budget, analytics, view, unknown
Priority order matters — more specific intents checked before generic ones.
"""
import re

DELETE_KEYWORDS    = {"delete", "remove", "cancel"}
UPDATE_KEYWORDS    = {"update", "change", "edit", "fix", "correct", "modify"}
ADD_KEYWORDS       = {"add", "spent", "paid", "pay", "bought", "buy",
                        "got", "received", "earned", "credited"}
BUDGET_KEYWORDS    = {"budget", "overspend", "overspending", "limit", "afford"}
SETTINGS_KEYWORDS  = {"config", "preference", "currency", "set income", "monthly income"}
ANALYTICS_KEYWORDS = {"top", "breakdown", "compare", "pattern", "trend",
                        "analysis", "most", "least", "highest", "lowest"}
VIEW_KEYWORDS      = {"show", "view", "list", "display", "transactions",
                        "summary", "how much", "this month", "last month"}


def classify_intent(message: str) -> str:
    """Classify user message into one of 8 intent categories.

    Args:
        message: Raw user message

    Returns:
        Intent string — one of: delete, update, add, budget,
        settings, analytics, view, unknown
    """
    normalized = message.lower()
    words      = set(re.sub(r"[^\w\s]", "", normalized).split())

    if words & DELETE_KEYWORDS:
        return "delete"

        # multi-word phrases — can't use set intersection
    if any(phrase in normalized for phrase in SETTINGS_KEYWORDS):
        return "settings"

    if words & UPDATE_KEYWORDS:
        return "update"

    if words & ADD_KEYWORDS:
        return "add"

    if words & BUDGET_KEYWORDS:
        return "budget"

    if words & ANALYTICS_KEYWORDS:
        return "analytics"

    if any(phrase in normalized for phrase in VIEW_KEYWORDS):
        return "view"

    return "unknown"