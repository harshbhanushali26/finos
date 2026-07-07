"""Tool Registry — maps tool names to Pydantic schemas and handler functions.

get_schemas() — returns all schemas to pass to Groq API
execute()     — dispatches tool call to correct handler
"""
from tools.tool_schemas import (
    AddTransaction, ViewTransactions, StageDelete, StageUpdate, 
    GetDailySummary, GetMonthlySummary, GetCategoryBreakdown, GetTopCategories, GetCategories,
    SetBudget, GetBudgetStatus, CheckOverspend, SuggestBudget,
    GetConfig, SetMonthlyIncome, SetPreference,
    pydantic_to_groq
)

from tools.tool_transactions import (add_transaction, stage_delete, stage_update, view_transactions)
from tools.tool_analytics import (get_daily_summary, get_monthly_summary, get_category_breakdown, get_top_categories, get_categories)
from tools.tool_budget import (set_budget, get_budget_status, check_overspend, suggest_budget)
from tools.tool_settings import (get_config, set_monthly_income, set_preference)

TOOL_REGISTRY = {
    "add_transaction": {
        "handler": add_transaction,
        "schema": pydantic_to_groq(AddTransaction, "add_transaction", "Add a new income or expense transaction"),
    },
    "stage_delete": {
    "handler": stage_delete,
    "schema": pydantic_to_groq(StageDelete, "stage_delete", "Find transactions matching filters (category, month, date, type) and stage them for deletion in one call. Do not call view_transactions first. Pass limit=1 if user says 'last' or 'latest'."),
    },
    "stage_update": {
        "handler": stage_update,
        "schema": pydantic_to_groq(StageUpdate, "stage_update", "Find transactions matching filters (category, month, date, type) and stage them for update with new_amount/new_category/new_date/new_note in one call. Do not call view_transactions first."),
    },
    "view_transactions": {
        "handler": view_transactions,
        "schema": pydantic_to_groq(ViewTransactions, "view_transactions", "View and filter transactions. Pass at least one filter — type_, category, date, from_date+to_date, or month"),
    },
    "get_daily_summary": {
        "handler": get_daily_summary,
        "schema": pydantic_to_groq(GetDailySummary, "get_daily_summary", "Get income, expense and balance summary for a specific day"),
    },
    "get_monthly_summary": {
        "handler": get_monthly_summary,
        "schema": pydantic_to_groq(GetMonthlySummary, "get_monthly_summary", "Get income, expense and balance summary for a month"),
    },
    "get_category_breakdown": {
        "handler": get_category_breakdown,
        "schema": pydantic_to_groq(GetCategoryBreakdown, "get_category_breakdown", "Get total amount per category. Required: type (income or expense) and month (YYYY-MM). Do not ask follow-up — default to expense if not specified."),
    },
    "get_top_categories": {
        "handler": get_top_categories,
        "schema": pydantic_to_groq(GetTopCategories, "get_top_categories", "Get top N expense categories for a month by total amount"),
    },
    "get_categories": {
        "handler": get_categories,
        "schema": pydantic_to_groq(GetCategories, "get_categories", "Get all income and expense category names for this user"),
    },
    "set_budget": {
        "handler": set_budget,
        "schema": pydantic_to_groq(SetBudget, "set_budget", "Set a monthly budget limit for a category"),
    },
    "get_budget_status": {
        "handler": get_budget_status,
        "schema": pydantic_to_groq(GetBudgetStatus, "get_budget_status", "Get current spending vs budget limit for all categories. Always pass month in YYYY-MM format."),
    },
    "check_overspend": {
        "handler": check_overspend,
        "schema": pydantic_to_groq(CheckOverspend, "check_overspend", "Check which categories exceeded or are near budget limit. Always pass month in YYYY-MM format."),
    },
    "suggest_budget": {
        "handler": suggest_budget,
        "schema": pydantic_to_groq(SuggestBudget, "suggest_budget", "Suggest monthly budget amounts based on last 3 months average spend per category"),
    },
    "get_config": {
        "handler": get_config,
        "schema": pydantic_to_groq(GetConfig, "get_config", "Get current user configuration"),
    },
    "set_monthly_income": {
        "handler": set_monthly_income,
        "schema": pydantic_to_groq(SetMonthlyIncome, "set_monthly_income", "Set the user monthly income amount"),
    },
    "set_preference": {
        "handler": set_preference,
        "schema": pydantic_to_groq(SetPreference, "set_preference", "Update a user preference like currency or date format"),
    },
}


def get_schemas() -> list:
    """Return all tool schemas as list to pass to Groq API."""
    return [tool["schema"] for tool in TOOL_REGISTRY.values()]


def execute(tool_name: str, args: dict, session) -> str:
    """Dispatch tool call to correct handler.
    
    Args:
        tool_name: Tool name from LLM response
        args:      Arguments dict from LLM
        session:   Current Session instance
        
    Returns:
        String result to send back to LLM
        
    Raises:
        ValueError: If tool not found in registry
    """
    if tool_name not in TOOL_REGISTRY:
        raise ValueError(f"Unknown tool: {tool_name}")

    handler = TOOL_REGISTRY[tool_name]["handler"]
    return handler(args, session)


# ── Intent → tool name mapping ─────────────────────────────────────────────────

INTENT_TOOLS = {
    "delete":    ["stage_delete"],
    "update":    ["stage_update"],
    "add":       ["add_transaction", "get_categories"],
    "view":      ["view_transactions", "get_daily_summary", "get_monthly_summary"],
    "analytics": ["get_category_breakdown", "get_top_categories", "get_monthly_summary"],
    "budget":    ["get_budget_status", "set_budget", "check_overspend", "suggest_budget"],
    "settings":  ["get_config", "set_monthly_income", "set_preference"],
}


def get_tools_for_intent(intent: str) -> list:
    """Return filtered tool schemas for a given intent.

    Args:
        intent: Intent string from classifier

    Returns:
        List of tool schemas to pass to Groq API.
        Falls back to all schemas for unknown intent.
    """
    if intent not in INTENT_TOOLS:
        return get_schemas()  # unknown → all 15
    names = INTENT_TOOLS[intent]
    return [TOOL_REGISTRY[name]["schema"] for name in names]