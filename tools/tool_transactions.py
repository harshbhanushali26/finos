"""Transaction tools — handler functions for add, view, stage_delete, stage_update, update, delete.

Each handler receives args dict from LLM and a Session instance.
All DB operations use session.db_session directly — no bridge.
"""

from datetime import datetime, date as dt_date
from sqlmodel import select

from core.models import Transaction, Category
from core import shared_txns


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ensure_category(name: str, txn_type: str, user_id: int, db) -> None:
    """Create category if it doesn't already exist for this user.
    Silent auto-create — used only by update_transaction. This is the
    documented deferred inconsistency (chained-confirmation complexity not
    worth it yet), deliberately NOT unified with add_transaction's
    confirm-before-create flow."""
    if not shared_txns.category_exists(db, user_id, name, txn_type):
        db.add(Category(user_id=user_id, name=name, type=txn_type, is_default=False))
        db.commit()


def _fmt_date(date_str: str) -> dt_date:
    """Parse YYYY-MM-DD string to date object."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


# ── Tool handlers ─────────────────────────────────────────────────────────────

def add_transaction(args: dict, session) -> str:
    """Handle add_transaction tool call."""
    try:
        txn_type = args.get("type") or args.get("type_")
        if not txn_type:
            return "Failed to add transaction — transaction type (income/expense) is required"

        db = session.db_session
        amount = float(args["amount"])
        category = args["category"]
        date_str = args["date"]
        note = args.get("description") or args.get("note") or ""

        if not shared_txns.category_exists(db, session.user_id, category, txn_type):
            session.state.set_pending_direct({
                "action_type": "new_category",
                "category": category,
                "txn_type": txn_type,
                "amount": amount,
                "date_str": date_str,
                "note": note,
            })
            return (
                f"'{category}' isn't a category yet. Create it and log this "
                f"{txn_type} of ₹{amount:,.0f} on {date_str}? Reply yes to confirm or no to cancel."
            )

        parsed_date = _fmt_date(date_str)
        existing = shared_txns.find_duplicate(
            db, session.user_id, txn_type, amount, category, parsed_date
        )

        shared_txns.insert_transaction(
            db, session.user_id, txn_type, amount, category, parsed_date, note=note,
        )

        if existing:
            return (
                f"⚠️ WARNING: possible duplicate detected — a {txn_type} of ₹{amount:,.0f} "
                f"for {category} on {date_str} already exists. Transaction was added — "
                f"you MUST inform the user about the possible duplicate."
            )

        return f"Transaction added — {txn_type} of ₹{amount:,.0f} for {category} on {date_str}"

    except Exception as e:
        return f"Error adding transaction: {str(e)}"


def view_transactions(args: dict, session) -> str:
    """View transactions — stores results in DependencyState for delete/update flows."""
    try:
        db = session.db_session
        stmt = select(Transaction).where(Transaction.user_id == session.user_id)

        txn_type = args.get("type") or args.get("type_")
        if txn_type:
            stmt = stmt.where(Transaction.type == txn_type)

        category = args.get("category")
        if category:
            stmt = stmt.where(Transaction.category == category)

        month = args.get("month")
        if month:
            year, mon = map(int, month.split("-"))
            from calendar import monthrange
            last_day = monthrange(year, mon)[1]
            month_start = dt_date(year, mon, 1)
            month_end = dt_date(year, mon, last_day)
            stmt = stmt.where(Transaction.date >= month_start, Transaction.date <= month_end)

        from_date = args.get("from_date")
        if from_date:
            stmt = stmt.where(Transaction.date >= _fmt_date(from_date))

        to_date = args.get("to_date")
        if to_date:
            stmt = stmt.where(Transaction.date <= _fmt_date(to_date))

        date_str = args.get("date")
        if date_str:
            stmt = stmt.where(Transaction.date == _fmt_date(date_str))

        stmt = stmt.order_by(Transaction.date.desc())
        transactions = db.exec(stmt).all()

        if not transactions:
            parts = []
            if txn_type:
                parts.append(txn_type)
            if category:
                parts.append(f"category '{category}'")
            if month:
                parts.append(f"month {month}")
            if date_str:
                parts.append(f"date {date_str}")
            filter_desc = " · ".join(parts) if parts else "given filters"
            return f"No transactions found for {filter_desc}"

        step_id = session.state.next_step()
        txn_list = []
        lines = []

        for i, txn in enumerate(transactions, 1):
            desc = f"₹{txn.amount:,.0f} {txn.category.title()} on {txn.date}"
            if txn.note:
                desc += f" — {txn.note}"
            txn_list.append({
                "txn_id": txn.id,
                "description": desc,
                "fields": {},
            })
            lines.append(f"{i}. {desc}")

        session.state.store(step_id, {
            "data": {
                "transactions": txn_list,
                "step_id": step_id,
            }
        })

        return f"Found {len(transactions)} transaction(s):\n" + "\n".join(lines)

    except Exception as e:
        return f"Error viewing transactions: {str(e)}"


def update_transaction(args: dict, session) -> str:
    """Handle update_transaction tool call — applies field changes to a specific transaction."""
    try:
        db = session.db_session
        txn_id = args["txn_id"]
        txn = shared_txns.get_owned_transaction(db, session.user_id, txn_id)

        if not txn:
            return f"Transaction {txn_id} not found"

        fields = {k: v for k, v in args.items() if k != "txn_id" and v is not None}
        if not fields:
            return "No fields provided to update"

        for key, value in fields.items():
            if key == "amount":
                txn.amount = float(value)
            elif key == "category":
                txn.category = value
                _ensure_category(value, txn.type, session.user_id, db)
            elif key == "date":
                txn.date = _fmt_date(value)
            elif key in ("note", "description"):
                txn.note = value
            elif key in ("type", "type_"):
                txn.type = value

        db.add(txn)
        db.commit()

        updated = ", ".join(f"{k}: {v}" for k, v in fields.items())
        return f"Transaction {txn_id} updated successfully — changed {updated}"

    except Exception as e:
        return f"Error updating transaction: {str(e)}"


def delete_transaction(args: dict, session) -> str:
    """Handle delete_transaction tool call."""
    try:
        db = session.db_session
        txn_id = args["txn_id"]
        txn = shared_txns.get_owned_transaction(db, session.user_id, txn_id)

        if not txn:
            return f"Transaction {txn_id} not found"

        db.delete(txn)
        db.commit()
        return f"Transaction {txn_id} deleted successfully"

    except Exception as e:
        return f"Error deleting transaction: {str(e)}"


def stage_delete(args: dict, session) -> str:
    """Look up matching transactions AND stage them for deletion in one call.
    Merges the old view_transactions -> stage_delete two-step into one,
    since the agent loop only allows one tool call per turn."""
    try:
        db = session.db_session
        stmt = select(Transaction).where(Transaction.user_id == session.user_id)

        txn_type = args.get("type") or args.get("type_")
        if txn_type:
            stmt = stmt.where(Transaction.type == txn_type)

        category = args.get("category")
        if category:
            stmt = stmt.where(Transaction.category == category)

        month = args.get("month")
        if month:
            year, mon = map(int, month.split("-"))
            from calendar import monthrange
            last_day = monthrange(year, mon)[1]
            stmt = stmt.where(Transaction.date >= dt_date(year, mon, 1),
                                Transaction.date <= dt_date(year, mon, last_day))

        date_str = args.get("date")
        if date_str:
            stmt = stmt.where(Transaction.date == _fmt_date(date_str))

        stmt = stmt.order_by(Transaction.date.desc(), Transaction.id.desc())
        transactions = db.exec(stmt).all()

        if not transactions:
            return "No matching transactions found for that description."

        limit = args.get("limit")
        if limit:
            transactions = transactions[:int(limit)]

        MAX_CANDIDATES = 10
        if len(transactions) > MAX_CANDIDATES:
            return (
                f"Found {len(transactions)} matching transactions — too many to list safely. "
                f"Please narrow it down with a date, month, or a smaller time range (e.g. "
                f"'delete my Utilities transaction today' or 'this month')."
            )

        candidates = []
        lines = []
        for i, txn in enumerate(transactions, 1):
            desc = f"₹{txn.amount:,.0f} {txn.category.title()} on {txn.date}"
            if txn.note:
                desc += f" — {txn.note}"
            candidates.append({"txn_id": txn.id, "description": desc, "fields": {}})
            lines.append(f"{i}. {desc}")

        session.state.set_candidates(candidates, action_type="delete")
        return "\n".join(lines) + "\n\nReply with a number to select which one to delete."

    except Exception as e:
        return f"Error staging delete: {str(e)}"


def stage_update(args: dict, session) -> str:
    """Look up matching transactions AND stage the field changes in one call.
    Merges the old view_transactions -> stage_update two-step into one."""
    try:
        db = session.db_session
        stmt = select(Transaction).where(Transaction.user_id == session.user_id)

        txn_type = args.get("type") or args.get("type_")
        if txn_type:
            stmt = stmt.where(Transaction.type == txn_type)

        category = args.get("category")
        if category:
            stmt = stmt.where(Transaction.category == category)

        month = args.get("month")
        if month:
            year, mon = map(int, month.split("-"))
            from calendar import monthrange
            last_day = monthrange(year, mon)[1]
            stmt = stmt.where(Transaction.date >= dt_date(year, mon, 1),
                                Transaction.date <= dt_date(year, mon, last_day))

        date_str = args.get("date")
        if date_str:
            stmt = stmt.where(Transaction.date == _fmt_date(date_str))

        stmt = stmt.order_by(Transaction.date.desc(), Transaction.id.desc())
        transactions = db.exec(stmt).all()

        if not transactions:
            return "No matching transactions found for that description."

        limit = args.get("limit")
        if limit:
            transactions = transactions[:int(limit)]

        # new field values to apply once a candidate is picked & confirmed
        update_fields = {}
        if args.get("new_amount") is not None:
            update_fields["amount"] = args["new_amount"]
        if args.get("new_category") is not None:
            update_fields["category"] = args["new_category"]
        if args.get("new_date") is not None:
            update_fields["date"] = args["new_date"]
        if args.get("new_note") is not None:
            update_fields["note"] = args["new_note"]

        if not update_fields:
            return "No new field values provided — specify what to change (amount, category, date, or note)."

        candidates = []
        lines = []
        for i, txn in enumerate(transactions, 1):
            desc = f"₹{txn.amount:,.0f} {txn.category.title()} on {txn.date}"
            if txn.note:
                desc += f" — {txn.note}"
            candidates.append({"txn_id": txn.id, "description": desc, "fields": dict(update_fields)})
            lines.append(f"{i}. {desc}")

        session.state.set_candidates(candidates, action_type="update")
        changes = ", ".join(f"{k} → {v}" for k, v in update_fields.items())
        return f"Changes to apply: {changes}\n\n" + "\n".join(lines) + "\n\nReply with a number to select which one to update."

    except Exception as e:
        return f"Error staging update: {str(e)}"


