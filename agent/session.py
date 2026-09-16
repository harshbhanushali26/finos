"""Session module — manages user context and conversation history for FinOS agent."""

import json
from pathlib import Path
from datetime import datetime

from agent.state import DependencyState
from sqlmodel import Session as DBSession, select

from agent.state import DependencyState
from core.models import AgentSessionRecord
from config import TOOL_RESULTS_TO_KEEP, TOOL_RESULT_TRIM_LENGTH


SYSTEM_PROMPT_FILEPATH = Path(__file__).parent / "prompts" / "system_prompt.md"


class Session:
    """Maintains session context for a single user conversation.

    Holds user_id, username, a live SQLModel DB session, conversation history,
    and DependencyState for delete/update flows. Created once per user at first
    chat request and reused across all subsequent requests for that conversation.

    Attributes:
        user_id:    Integer user PK from the DB
        username:   Display name for system prompt injection
        db_session: SQLModel Session — used by all tool functions for DB access
        history:    List of message dicts passed to Groq API
        state:      DependencyState instance for delete/update flows
        created_at: Datetime when the session was created
    """

    def __init__(self, user_id: int, username: str, db_session: DBSession):
        self.user_id = user_id
        self.username = username
        self.db_session = db_session
        self.history = []
        self.created_at = datetime.now()
        # self.state = DependencyState()
        self.state = DependencyState(user_id=self.user_id, db=self.db_session)

    # ── History management ─────────────────────────────────────────────────────

    def add_message(self, role: str, content: str):
        """Append a plain message to conversation history."""
        self.history.append({"role": role, "content": content})

    def get_history(self) -> list:
        """Return full conversation history for Groq API."""
        return self.history

    def clear_history(self):
        """Reset conversation history, preserving the system prompt if present."""
        if self.history and self.history[0]["role"] == "system":
            self.history = [self.history[0]]
        else:
            self.history = []
        self.state.clear()

    def add_system_prompt(self, filepath: Path = SYSTEM_PROMPT_FILEPATH):
        """Read system prompt from file, inject dynamic values, prepend to history.

        Raises:
            FileNotFoundError: If system_prompt.md is missing
            KeyError: If a placeholder in the prompt has no matching value
        """
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                prompt = f.read()

            today = datetime.now().strftime("%Y-%m-%d")
            current_month = datetime.now().strftime("%Y-%m")

            filled_prompt = prompt.format(
                username=self.username,
                today=today,
                current_month=current_month,
            )

            self.add_message("system", filled_prompt)

        except FileNotFoundError:
            raise FileNotFoundError(f"System prompt not found at {filepath}")
        except KeyError as e:
            raise KeyError(f"Missing placeholder in system prompt: {e}")

    # ── Assistant / tool message helpers ──────────────────────────────────────

    def add_assistant_message(self, message):
        """Append assistant message with tool_calls to history in Groq format."""
        tool_calls = message.tool_calls or []
        self.history.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ],
        })

    def add_tool_result(self, tool_call_id: str, name: str, content: str):
        """Append tool result to history in Groq-required format."""
        self.history.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": name,
            "content": content,
        })

    # ── Token management ──────────────────────────────────────────────────────

    def trim_old_tool_results(self):
        """Truncate old tool result content to save tokens.

        Keeps the last TOOL_RESULTS_TO_KEEP results intact; truncates older ones
        to TOOL_RESULT_TRIM_LENGTH characters.
        """
        tool_indices = [
            i for i, m in enumerate(self.history) if m.get("role") == "tool"
        ]
        to_trim = (
            tool_indices[:-TOOL_RESULTS_TO_KEEP]
            if len(tool_indices) > TOOL_RESULTS_TO_KEEP
            else []
        )
        for i in to_trim:
            content = self.history[i].get("content", "")
            if len(content) > TOOL_RESULT_TRIM_LENGTH:
                self.history[i]["content"] = content[:TOOL_RESULT_TRIM_LENGTH] + "... [trimmed]"

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def message_count(self) -> int:
        """Total number of messages in history."""
        return len(self.history)

    def get_last_message(self) -> dict | None:
        """Return the last message in history, or None if empty."""
        return self.history[-1] if self.history else None

    # In agent/session.py:
    def _load_history(self) -> list:
        record = self.db_session.exec(
            select(AgentSessionRecord).where(AgentSessionRecord.user_id == self.user_id)
        ).first()
        if not record:
            record = AgentSessionRecord(user_id=self.user_id, history_json="[]")
            self.db_session.add(record)
            self.db_session.commit()
            return []
        return json.loads(record.history_json)

    def _save_history(self):
        record = self.db_session.exec(
            select(AgentSessionRecord).where(AgentSessionRecord.user_id == self.user_id)
        ).first()
        if record:
            record.history_json = json.dumps(self.history)
            self.db_session.add(record)
            self.db_session.commit()