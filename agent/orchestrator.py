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
from tools.tool_transactions import add_transaction, delete_transaction, update_transaction, _ensure_category


# ── Confirm executor ──────────────────────────────────────────────────────────

def _execute_pending(session) -> str:
    """Execute the confirmed delete, update, or new-category action directly via tool functions."""
    action = session.state.confirm()
    if not action:
        return "Nothing to confirm."

    try:
        if action["action_type"] == "delete":
            result = delete_transaction({"txn_id": action["txn_id"]}, session)
            return f"Deleted — {action['description']}." if "successfully" in result else f"Failed — {result}"

        elif action["action_type"] == "update":
            args = {"txn_id": action["txn_id"], **action["fields"]}
            result = update_transaction(args, session)
            changes = ", ".join(f"{k} → {v}" for k, v in action["fields"].items())
            return f"Updated — {action['description']}. Changed {changes}." if "successfully" in result else f"Failed — {result}"

        elif action["action_type"] == "new_category":
            _ensure_category(action["category"], action["txn_type"], session.user_id, session.db_session)
            result = add_transaction({
                "type": action["txn_type"],
                "amount": action["amount"],
                "category": action["category"],
                "date": action["date_str"],
                "note": action["note"],
            }, session)
            return result

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