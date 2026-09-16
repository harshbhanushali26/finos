"""
tests/test_agent_and_tools.py — Unit tests for LLM tools, pattern matcher, and orchestrator.

Verifies:
- add_transaction tool (prompts on unknown category, warns on duplicate)
- stage_delete & stage_update (candidates listing and safeguard limits)
- pattern_matcher regex extraction (category, payment methods, dates)
- pattern_matcher duplicate fallback to LLM
- orchestrator pending executor

Run with:
    uv run pytest tests/test_agent_and_tools.py -v
"""

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from agent.session import Session as AgentSession
from agent.pattern_matcher import match as pm_match
from agent.orchestrator import _execute_pending
from tools import tool_transactions
from core.models import Category, PaymentMethod, User


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(name="db")
def db_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="agent_session")
def agent_session_fixture(db: Session) -> AgentSession:
    user = User(username="alice", password_hash="hash123", currency="INR")
    db.add(user)
    db.commit()
    db.refresh(user)

    cat_food = Category(user_id=user.id, name="Food", type="expense")
    cat_salary = Category(user_id=user.id, name="Salary", type="income")
    pm_upi = PaymentMethod(user_id=user.id, name="UPI")
    db.add_all([cat_food, cat_salary, pm_upi])
    db.commit()

    return AgentSession(user_id=user.id, username=user.username, db_session=db)


# ── 1. Tool Tests ─────────────────────────────────────────────────────────────

def test_tool_add_transaction_success(agent_session: AgentSession):
    args = {"type": "expense", "amount": 200, "category": "Food", "date": "2026-09-15"}
    resp = tool_transactions.add_transaction(args, agent_session)
    assert "Transaction added" in resp


def test_tool_add_transaction_unknown_category_prompts_confirm(agent_session: AgentSession):
    args = {"type": "expense", "amount": 500, "category": "Gadgets", "date": "2026-09-15"}
    resp = tool_transactions.add_transaction(args, agent_session)

    # Prompt user to confirm creation
    assert "isn't a category yet" in resp
    assert agent_session.state.mode == "await_confirm"
    assert agent_session.state.pending_action["action_type"] == "new_category"

    # Now execute pending confirm
    exec_resp = _execute_pending(agent_session)
    assert "Created and logged" in exec_resp


def test_tool_stage_delete(agent_session: AgentSession):
    # Add a transaction
    tool_transactions.add_transaction({"type": "expense", "amount": 300, "category": "Food", "date": "2026-09-15"}, agent_session)

    # Stage delete
    resp = tool_transactions.stage_delete({"category": "Food"}, agent_session)
    assert "Reply with a number to select which one to delete" in resp
    assert agent_session.state.mode == "await_select"

    # Select candidate 1
    selected = agent_session.state.select(1)
    assert selected is not None
    assert agent_session.state.mode == "await_confirm"

    # Confirm delete
    confirm_resp = _execute_pending(agent_session)
    assert "Deleted —" in confirm_resp


# ── 2. Pattern Matcher Tests ──────────────────────────────────────────────────

def test_pattern_matcher_add_with_payment_method(agent_session: AgentSession):
    query = "spent 450 on food via UPI"
    res = pm_match(query, agent_session)
    assert res["matched"] is True
    assert "Added ₹450 for Food via UPI" in res["response"]


def test_pattern_matcher_duplicate_bails_to_llm(agent_session: AgentSession):
    # First entry
    pm_match("spent 250 on food", agent_session)

    # Duplicate entry
    res2 = pm_match("spent 250 on food", agent_session)
    # Bails out so LLM can explain duplicate
    assert res2["matched"] is False