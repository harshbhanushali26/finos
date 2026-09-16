"""
Transaction tools — handler functions for add, view, stage_delete, stage_update, update, delete.

Thin adapter over core/services.py:
Translates LLM tool arguments into service calls and formats natural language prompt responses.
"""

from core.services import (
    ServiceStatus,
    create_transaction as service_create_transaction,
    get_transactions as service_get_transactions,
    update_transaction as service_update_transaction,
    delete_transaction as service_delete_transaction,
    ensure_category,
)

_ensure_category = ensure_category

# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_txn_desc(txn) -> str:
    """Format a single transaction line for chat display."""
    desc = f"₹{txn.amount:,.0f} {txn.category.title()} on {txn.date}"
    if txn.payment_method:
        desc += f" (via {txn.payment_method})"
    if txn.note:
        desc += f" — {txn.note}"
    return desc


# ── Tool handlers ─────────────────────────────────────────────────────────────

def add_transaction(args: dict, session) -> str:
    """Handle add_transaction tool call."""
    try:
        txn_type = args.get("type") or args.get("type_")
        if not txn_type:
            return "Failed to add transaction — transaction type (income/expense) is required"

        amount = float(args["amount"])
        category = args["category"]
        date_str = args["date"]
        note = args.get("description") or args.get("note") or ""
        payment_method = args.get("payment_method")

        result = service_create_transaction(
            db=session.db_session,
            user_id=session.user_id,
            type_=txn_type,
            amount=amount,
            category=category,
            date=date_str,
            note=note,
            payment_method=payment_method,
            allow_create_category=False,
            allow_create_payment_method=False,
        )

        if result.status == ServiceStatus.CATEGORY_NOT_FOUND:
            session.state.set_pending_direct({
                "action_type": "new_category",
                "category": category,
                "txn_type": txn_type,
                "amount": amount,
                "date_str": date_str,
                "note": note,
                "payment_method": payment_method,
            })
            return (
                f"'{category}' isn't a category yet. Create it and log this "
                f"{txn_type} of ₹{amount:,.0f} on {date_str}? Reply yes to confirm or no to cancel."
            )

        if result.status == ServiceStatus.PAYMENT_METHOD_NOT_FOUND:
            session.state.set_pending_direct({
                "action_type": "new_payment_method",
                "category": category,
                "txn_type": txn_type,
                "amount": amount,
                "date_str": date_str,
                "note": note,
                "payment_method": payment_method,
            })
            return (
                f"'{payment_method}' isn't a registered payment method yet. Add it and log this "
                f"{txn_type} of ₹{amount:,.0f} on {date_str}? Reply yes to confirm or no to cancel."
            )

        if result.status == ServiceStatus.VALIDATION_ERROR:
            return f"Error adding transaction: {result.error_message}"

        pm_suffix = f" via {payment_method}" if payment_method else ""
        if result.is_duplicate:
            return (
                f"⚠️ WARNING: possible duplicate detected — a {txn_type} of ₹{amount:,.0f} "
                f"for {category} on {date_str} already exists. Transaction was added — "
                f"you MUST inform the user about the possible duplicate."
            )

        return f"Transaction added — {txn_type} of ₹{amount:,.0f} for {category} on {date_str}{pm_suffix}"

    except Exception as e:
        return f"Error adding transaction: {str(e)}"


def view_transactions(args: dict, session) -> str:
    """View transactions — stores results in DependencyState for delete/update flows."""
    try:
        txn_type = args.get("type") or args.get("type_")
        category = args.get("category")
        payment_method = args.get("payment_method")
        month = args.get("month")
        from_date = args.get("from_date")
        to_date = args.get("to_date")
        date_str = args.get("date")

        result = service_get_transactions(
            db=session.db_session,
            user_id=session.user_id,
            type_=txn_type,
            category=category,
            payment_method=payment_method,
            date=date_str,
            date_from=from_date,
            date_to=to_date,
            month=month,
        )

        if result.status == ServiceStatus.VALIDATION_ERROR:
            return f"Error viewing transactions: {result.error_message}"

        if not result.transactions:
            parts = []
            if txn_type:
                parts.append(txn_type)
            if category:
                parts.append(f"category '{category}'")
            if payment_method:
                parts.append(f"payment method '{payment_method}'")
            if month:
                parts.append(f"month {month}")
            if date_str:
                parts.append(f"date {date_str}")
            filter_desc = " · ".join(parts) if parts else "given filters"
            return f"No transactions found for {filter_desc}"

        step_id = session.state.next_step()
        txn_list = []
        lines = []

        for i, txn in enumerate(result.transactions, 1):
            desc = _format_txn_desc(txn)
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

        return f"Found {len(result.transactions)} transaction(s):\n" + "\n".join(lines)

    except Exception as e:
        return f"Error viewing transactions: {str(e)}"


def update_transaction(args: dict, session) -> str:
    """Handle update_transaction tool call — applies field changes to a specific transaction."""
    try:
        txn_id = int(args["txn_id"])
        amount = float(args["amount"]) if "amount" in args and args["amount"] is not None else None
        category = args.get("category")
        date_val = args.get("date")
        note = args.get("description") or args.get("note")
        txn_type = args.get("type") or args.get("type_")
        payment_method = args.get("payment_method")

        result = service_update_transaction(
            db=session.db_session,
            user_id=session.user_id,
            txn_id=txn_id,
            amount=amount,
            type_=txn_type,
            category=category,
            date=date_val,
            note=note,
            payment_method=payment_method,
            allow_create_category=True,  # Retains chat auto-create policy
            allow_create_payment_method=True,
        )

        if result.status == ServiceStatus.NOT_FOUND:
            return f"Transaction {txn_id} not found"

        if result.status == ServiceStatus.NO_FIELDS_TO_UPDATE:
            return "No fields provided to update"

        if result.status == ServiceStatus.VALIDATION_ERROR:
            return f"Error updating transaction: {result.error_message}"

        updated = ", ".join(f"{k}: {v}" for k, v in result.updated_fields.items())
        return f"Transaction {txn_id} updated successfully — changed {updated}"

    except Exception as e:
        return f"Error updating transaction: {str(e)}"


def delete_transaction(args: dict, session) -> str:
    """Handle delete_transaction tool call."""
    try:
        txn_id = int(args["txn_id"])
        result = service_delete_transaction(
            db=session.db_session,
            user_id=session.user_id,
            txn_id=txn_id,
        )

        if result.status == ServiceStatus.NOT_FOUND:
            return f"Transaction {txn_id} not found"

        return f"Transaction {txn_id} deleted successfully"

    except Exception as e:
        return f"Error deleting transaction: {str(e)}"


def stage_delete(args: dict, session) -> str:
    """Look up matching transactions AND stage them for deletion in one call."""
    try:
        txn_type = args.get("type") or args.get("type_")
        category = args.get("category")
        payment_method = args.get("payment_method")
        month = args.get("month")
        date_str = args.get("date")
        limit = int(args["limit"]) if args.get("limit") else None

        result = service_get_transactions(
            db=session.db_session,
            user_id=session.user_id,
            type_=txn_type,
            category=category,
            payment_method=payment_method,
            month=month,
            date=date_str,
            limit=limit,
            max_candidates=10,
        )

        if result.status == ServiceStatus.TOO_MANY_CANDIDATES:
            return (
                f"Found {result.total_count} matching transactions — too many to list safely. "
                f"Please narrow it down with a date, month, or a smaller time range (e.g. "
                f"'delete my Utilities transaction today' or 'this month')."
            )

        if not result.transactions:
            return "No matching transactions found for that description."

        candidates = []
        lines = []
        for i, txn in enumerate(result.transactions, 1):
            desc = _format_txn_desc(txn)
            candidates.append({"txn_id": txn.id, "description": desc, "fields": {}})
            lines.append(f"{i}. {desc}")

        session.state.set_candidates(candidates, action_type="delete")
        return "\n".join(lines) + "\n\nReply with a number to select which one to delete."

    except Exception as e:
        return f"Error staging delete: {str(e)}"


def stage_update(args: dict, session) -> str:
    """Look up matching transactions AND stage the field changes in one call."""
    try:
        txn_type = args.get("type") or args.get("type_")
        category = args.get("category")
        payment_method = args.get("payment_method")
        month = args.get("month")
        date_str = args.get("date")
        limit = int(args["limit"]) if args.get("limit") else None

        # Build proposed field changes
        update_fields = {}
        if args.get("new_amount") is not None:
            update_fields["amount"] = args["new_amount"]
        if args.get("new_category") is not None:
            update_fields["category"] = args["new_category"]
        if args.get("new_date") is not None:
            update_fields["date"] = args["new_date"]
        if args.get("new_note") is not None:
            update_fields["note"] = args["new_note"]
        if args.get("new_payment_method") is not None:
            update_fields["payment_method"] = args["new_payment_method"]

        if not update_fields:
            return "No new field values provided — specify what to change (amount, category, date, payment method, or note)."

        result = service_get_transactions(
            db=session.db_session,
            user_id=session.user_id,
            type_=txn_type,
            category=category,
            payment_method=payment_method,
            month=month,
            date=date_str,
            limit=limit,
            max_candidates=10,
        )

        if result.status == ServiceStatus.TOO_MANY_CANDIDATES:
            return (
                f"Found {result.total_count} matching transactions — too many to list safely. "
                f"Please narrow it down with a date, month, or a smaller time range."
            )

        if not result.transactions:
            return "No matching transactions found for that description."

        candidates = []
        lines = []
        for i, txn in enumerate(result.transactions, 1):
            desc = _format_txn_desc(txn)
            candidates.append({"txn_id": txn.id, "description": desc, "fields": dict(update_fields)})
            lines.append(f"{i}. {desc}")

        session.state.set_candidates(candidates, action_type="update")
        changes = ", ".join(f"{k} → {v}" for k, v in update_fields.items())
        return f"Changes to apply: {changes}\n\n" + "\n".join(lines) + "\n\nReply with a number to select which one to update."

    except Exception as e:
        return f"Error staging update: {str(e)}"