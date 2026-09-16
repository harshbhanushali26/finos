"""
agent/orchestrator.py — central message router for FinOS chat.

Sits between api/routes/chat.py (HTTP layer) and agent/llm.py (Groq LLM).
Handles all pre-LLM logic so the LLM is only called when truly needed.

Flow:
    1. State machine check (await_select / await_confirm)
    2. Special commands (clear)
    3. Pattern matcher
    4. LLM fallthrough (agent/llm.py)
"""

from agent import llm as agent_llm
from agent.pattern_matcher import match as pm_match
from core.services import (
    ServiceStatus,
    create_transaction as service_create_transaction,
    update_transaction as service_update_transaction,
    delete_transaction as service_delete_transaction,
)


# ── Confirm executor ──────────────────────────────────────────────────────────
def _execute_pending(session) -> str:
    """Execute confirmed delete, update, or new-category action directly via core.services."""
    action = session.state.confirm()
    if not action:
        return "Nothing to confirm."

    try:
        if action["action_type"] == "delete":
            res = service_delete_transaction(session.db_session, session.user_id, action["txn_id"])
            if res.status == ServiceStatus.SUCCESS:
                return f"Deleted — {action['description']}."
            return f"Failed — {res.error_message or 'Transaction not found'}."

        elif action["action_type"] == "update":
            res = service_update_transaction(
                session.db_session,
                session.user_id,
                action["txn_id"],
                amount=action["fields"].get("amount"),
                type_=action["fields"].get("type"),
                category=action["fields"].get("category"),
                date=action["fields"].get("date"),
                note=action["fields"].get("note"),
                payment_method=action["fields"].get("payment_method"),
                allow_create_category=True,
                allow_create_payment_method=True,
            )
            if res.status == ServiceStatus.SUCCESS:
                changes = ", ".join(f"{k} → {v}" for k, v in action["fields"].items())
                return f"Updated — {action['description']}. Changed {changes}."
            return f"Failed — {res.error_message}."

        elif action["action_type"] in ("new_category", "new_payment_method"):
            res = service_create_transaction(
                session.db_session,
                session.user_id,
                type_=action["txn_type"],
                amount=action["amount"],
                category=action["category"],
                date=action["date_str"],
                note=action.get("note", ""),
                payment_method=action.get("payment_method"),
                allow_create_category=True,
                allow_create_payment_method=True,
            )
            if res.status in (ServiceStatus.CREATED, ServiceStatus.DUPLICATE_DETECTED):
                pm_str = f" via {action['payment_method']}" if action.get("payment_method") else ""
                warn = " (⚠️ possible duplicate)" if res.is_duplicate else ""
                return (
                    f"Created and logged — {action['txn_type']} of ₹{action['amount']:,.0f} "
                    f"for {action['category']} on {action['date_str']}{pm_str}.{warn}"
                )
            return f"Failed: {res.error_message}"

    except Exception as e:
        return f"Action failed: {str(e)}"

    return "Unknown action type."


# ── Main entry point ──────────────────────────────────────────────────────────

def run(message: str, session) -> str:
    """
    Route a user message through the full decision tree.
    Returns a plain string — caller streams it via SSE.

    Args:
        message: Raw user input string
        session: Active Session instance (holds history + DependencyState)

    Returns:
        Response string to stream back to the user
    """
    text = message.strip()
    lower = text.lower()

    # ── AWAIT_SELECT — user picking a number from delete/update list ──────────
    if session.state.mode == "await_select":

        if text.isdigit():
            number = int(text)
            pending = session.state.select(number)
            if pending:
                if pending["action_type"] == "delete":
                    return f"Delete {pending['description']}? Reply yes to confirm or no to cancel."
                elif pending["action_type"] == "update":
                    changes = ", ".join(f"{k} → {v}" for k, v in pending["fields"].items())
                    return f"Update {pending['description']} — change {changes}? Reply yes to confirm or no to cancel."
            else:
                return "Invalid number — pick from the list above."

        if lower == "clear":
            session.clear_history()
            return "Conversation history cleared."

        if lower in ("cancel", "stop", "nevermind", "never mind"):
            session.state.reset()
            return "Cancelled — nothing changed."

        # anything else non-digit — don't silently wipe state, ask again
        return "Please reply with a number from the list above, or say 'cancel'."

    # ── AWAIT_CONFIRM — user saying yes/no ────────────────────────────────────
    if session.state.mode == "await_confirm":

        if lower in ("yes", "y", "confirm", "ok", "sure", "do it"):
            return _execute_pending(session)

        if lower in ("no", "n", "cancel", "stop", "nope"):
            session.state.cancel()
            return "Cancelled — nothing changed."

        if lower == "clear":
            session.clear_history()
            return "Conversation history cleared."

        return "Reply yes to confirm or no to cancel."

    # ── IDLE ──────────────────────────────────────────────────────────────────

    if lower == "clear":
        session.clear_history()
        return "Conversation history cleared."

    # Pattern matcher — 0 LLM calls for ~60% of queries
    result = pm_match(text, session)
    if result["matched"]:
        return result["response"]

    # LLM fallthrough — only reached if nothing above matched
    return agent_llm.run(text, session)