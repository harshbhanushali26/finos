"""Transaction tools — handler functions for add, view, stage_delete, stage_update, update, delete.

Each handler receives args dict from LLM and a Session instance.
All DB operations use session.db_session directly — no bridge.
"""

from datetime import datetime, date as dt_date
from sqlmodel import select

from core.models import Transaction, Category


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ensure_category(name: str, txn_type: str, user_id: int, db) -> None:
    """Create category if it doesn't already exist for this user."""
    existing = db.exec(
        select(Category).where(
            Category.user_id == user_id,
            Category.name == name,
            Category.type == txn_type,
        )
    ).first()
    if not existing:
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

        _ensure_category(category, txn_type, session.user_id, db)

        # duplicate detection — same type/amount/category/date within this user
        parsed_date = _fmt_date(date_str)
        existing = db.exec(
            select(Transaction).where(
                Transaction.user_id == session.user_id,
                Transaction.type == txn_type,
                Transaction.amount == amount,
                Transaction.category == category,
                Transaction.date == parsed_date,
            )
        ).first()

        txn = Transaction(
            user_id=session.user_id,
            amount=amount,
            type=txn_type,
            category=category,
            date=parsed_date,
            note=note,
        )
        db.add(txn)
        db.commit()
        db.refresh(txn)

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

        # month filter: "2026-06" → match date between first and last of month
        month = args.get("month")
        if month:
            year, mon = map(int, month.split("-"))
            from calendar import monthrange
            last_day = monthrange(year, mon)[1]
            month_start = dt_date(year, mon, 1)
            month_end = dt_date(year, mon, last_day)
            stmt = stmt.where(Transaction.date >= month_start, Transaction.date <= month_end)

        # explicit date range — from_date and to_date (from ViewTransactions schema)
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

        # store in dependency state — step 1 of delete/update flow
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
        txn = db.get(Transaction, txn_id)

        if not txn or txn.user_id != session.user_id:
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
        txn = db.get(Transaction, txn_id)

        if not txn or txn.user_id != session.user_id:
            return f"Transaction {txn_id} not found"

        db.delete(txn)
        db.commit()
        return f"Transaction {txn_id} deleted successfully"

    except Exception as e:
        return f"Error deleting transaction: {str(e)}"


def stage_delete(args: dict, session) -> str:
    """Stage transactions for deletion — resolves from last view_transactions step."""
    try:
        latest_step = session.state._step_counter
        if not session.state.has_step(latest_step):
            return "No transactions staged. Please call view_transactions first."

        step_output = session.state.get_step_output(latest_step)
        candidates = step_output["data"]["transactions"]

        if not candidates:
            return "No matching transactions found."

        session.state.set_candidates(candidates, action_type="delete")
        lines = [f"{i}. {c['description']}" for i, c in enumerate(candidates, 1)]
        return "Staged for deletion. Show this list to user exactly:\n" + "\n".join(lines) + "\nAsk user to reply with a number."

    except Exception as e:
        return f"Error staging delete: {str(e)}"


def stage_update(args: dict, session) -> str:
    """Stage transactions for update — stores field changes in candidates."""
    try:
        latest_step = session.state._step_counter
        if not session.state.has_step(latest_step):
            return "No transactions staged. Please call view_transactions first."

        step_output = session.state.get_step_output(latest_step)
        candidates = step_output["data"]["transactions"]

        if not candidates:
            return "No matching transactions found."

        update_fields = {k: v for k, v in args.items() if k != "step_id" and v is not None}
        for c in candidates:
            c["fields"] = update_fields

        session.state.set_candidates(candidates, action_type="update")
        lines = [f"{i}. {c['description']}" for i, c in enumerate(candidates, 1)]
        return "Staged for update. Show this list to user exactly:\n" + "\n".join(lines) + "\nAsk user to reply with a number."

    except Exception as e:
        return f"Error staging update: {str(e)}"