"""Tool schemas — Pydantic models for all LLM-callable tools.

Each model defines the input structure for one tool.
Converter transforms Pydantic schema to Groq-compatible format.
"""

from pydantic import BaseModel, Field
from typing import Literal, Optional


# ── Converter ─────────────────────────────────────────────────────────────────

def clean_property(prop: dict) -> dict:
    """Clean a single property dict — remove Pydantic-specific keys,
    flatten anyOf for optional fields.
    
    Args:
        prop: Single property dict from Pydantic schema
        
    Returns:
        Clean property dict Groq understands
    """
    cleaned = {}

    # flatten anyOf — optional fields come as {"anyOf": [{"type": "string"}, {"type": "null"}]}
    if "anyOf" in prop:
        for option in prop["anyOf"]:
            if option.get("type") != "null":
                cleaned.update(option)
                break
        cleaned.pop("anyOf", None)
    else:
        cleaned.update(prop)

    # remove Pydantic-specific keys Groq doesn't understand
    for key in ["title", "$ref", "$defs", "default"]:
        cleaned.pop(key, None)

    return cleaned


def pydantic_to_groq(model: type[BaseModel], name: str, description: str) -> dict:
    """Convert a Pydantic model to Groq-compatible tool schema.
    
    Args:
        model:       Pydantic BaseModel class
        name:        Tool name — must match handler name in registry
        description: Tool description shown to LLM
        
    Returns:
        Groq-compatible tool schema dict
    """
    raw = model.model_json_schema()

    cleaned_properties = {
        field: clean_property(prop)
        for field, prop in raw.get("properties", {}).items()
    }

    # rename type_ → type so model always sends "type"
    if "type_" in cleaned_properties:
        cleaned_properties["type"] = cleaned_properties.pop("type_")

    required = [r.replace("type_", "type") for r in raw.get("required", [])]

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": cleaned_properties,
                "required": required
            }
        }
    }


# ── Transaction Schemas ────────────────────────────────────────────────────────

class AddTransaction(BaseModel):
    type_: Literal["income", "expense"] = Field(description="Type of transaction")
    amount: float = Field(description="Transaction amount in INR")
    category: str = Field(description="Category name e.g. food, transport, salary")
    date: str = Field(description="Date in YYYY-MM-DD format")
    description: Optional[str] = Field(default=None, description="Optional short description")


class UpdateTransaction(BaseModel):
    txn_id: str = Field(description="Transaction UUID to update")
    amount: Optional[float] = Field(default=None, description="New amount")
    category: Optional[str] = Field(default=None, description="New category")
    date: Optional[str] = Field(default=None, description="New date in YYYY-MM-DD format")
    description: Optional[str] = Field(default=None, description="New description")
    type_: Optional[Literal["income", "expense"]] = Field(default=None, description="New transaction type")


class DeleteTransaction(BaseModel):
    txn_id: str = Field(description="Transaction UUID to delete")


class ViewTransactions(BaseModel):
    type_: Optional[Literal["income", "expense"]] = Field(default=None, description="Filter by type")
    category: Optional[str] = Field(default=None, description="Filter by category")
    date: Optional[str] = Field(default=None, description="Exact date YYYY-MM-DD")
    from_date: Optional[str] = Field(default=None, description="Start of date range YYYY-MM-DD")
    to_date: Optional[str] = Field(default=None, description="End of date range YYYY-MM-DD")
    month: Optional[str] = Field(default=None, description="Filter by month YYYY-MM")


# ── Analytics Schemas ──────────────────────────────────────────────────────────

class GetDailySummary(BaseModel):
    date: str = Field(description="Date in YYYY-MM-DD format")


class GetMonthlySummary(BaseModel):
    month: str = Field(description="Month in YYYY-MM format e.g. 2026-02")


class GetCategoryBreakdown(BaseModel):
    type_: Literal["income", "expense"] = Field(description="Transaction type — must be 'income' or 'expense'. Use 'expense' if not specified by user.")
    month: Optional[str] = Field(default=None, description="Month YYYY-MM, defaults to current month")


class GetTopCategories(BaseModel):
    month: str = Field(description="Month in YYYY-MM format")
    top_n: Optional[int] = Field(default=5, description="Number of top categories to return")


class GetCategories(BaseModel):
    pass


# ── Budget Schemas ─────────────────────────────────────────────────────────────

class SetBudget(BaseModel):
    category: str = Field(description="Category name to set budget for")
    limit: float = Field(description="Budget limit in INR")
    month: Optional[str] = Field(default=None, description="Month YYYY-MM, defaults to current month")


class GetBudgetStatus(BaseModel):
    month: str = Field(description="Month in YYYY-MM format e.g. 2026-02")


class CheckOverspend(BaseModel):
    month: str = Field(description="Month in YYYY-MM format e.g. 2026-02")


class SuggestBudget(BaseModel):
    pass


# ── Settings Schemas ─────────────────────────────────────────────────────────────

class GetConfig(BaseModel):
    model_config = {"json_schema_extra": {"properties": {}, "required": []}}


class SetMonthlyIncome(BaseModel):
    amount: float = Field(description="Monthly income in INR")


class SetPreference(BaseModel):
    key: str = Field(description="Preference key e.g. currency, date_format")
    value: str = Field(description="New value for the preference")


# ── Dependency + txn Schemas ─────────────────────────────────────────────────────────────


class StageDelete(BaseModel):
    pass  # no args needed — reads from DependencyState internally

class StageUpdate(BaseModel):
    amount: Optional[float] = Field(default=None, description="New amount")
    category: Optional[str] = Field(default=None, description="New category")
    date: Optional[str] = Field(default=None, description="New date YYYY-MM-DD")
    description: Optional[str] = Field(default=None, description="New description")
    type_: Optional[Literal["income", "expense"]] = Field(default=None, description="New type")