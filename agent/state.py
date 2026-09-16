import json
from typing import Any, Dict, List, Optional
from sqlmodel import Session, select
from core.models import AgentPendingAction


class DependencyState:
    """DB-persisted state machine managing interactive delete, update, and confirmation flows."""

    def __init__(self, user_id: int, db: Session):
        self.user_id = user_id
        self.db = db
        self._record: AgentPendingAction = self._get_or_create_record()

    def _get_or_create_record(self) -> AgentPendingAction:
        record = self.db.exec(
            select(AgentPendingAction).where(AgentPendingAction.user_id == self.user_id)
        ).first()
        if not record:
            record = AgentPendingAction(user_id=self.user_id)
            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)
        return record

    def rebind(self, db: Session):
        """Rebind to a fresh request-scoped DB session."""
        self.db = db
        self._record = self._get_or_create_record()

    @property
    def mode(self) -> str:
        return self._record.mode

    @property
    def pending_action(self) -> Optional[Dict]:
        return json.loads(self._record.payload_json) if self._record.payload_json != "{}" else None

    @property
    def candidates(self) -> List[Dict]:
        return json.loads(self._record.candidates_json)

    def set_candidates(self, candidates: List[Dict], action_type: str):
        c_list = [{**c, "action_type": action_type} for c in candidates]
        self._record.candidates_json = json.dumps(c_list)
        self._record.mode = "await_select"
        self._record.action_type = action_type
        self.db.add(self._record)
        self.db.commit()

    def set_pending_direct(self, action: Dict):
        self._record.payload_json = json.dumps(action)
        self._record.candidates_json = "[]"
        self._record.mode = "await_confirm"
        self._record.action_type = action.get("action_type")
        self.db.add(self._record)
        self.db.commit()

    def select(self, number: int) -> Optional[Dict]:
        candidates = self.candidates
        idx = number - 1
        if idx < 0 or idx >= len(candidates):
            return None

        chosen = candidates[idx]
        action = {
            "action_type": chosen["action_type"],
            "txn_id": chosen["txn_id"],
            "description": chosen["description"],
            "fields": chosen.get("fields", {}),
        }
        self._record.payload_json = json.dumps(action)
        self._record.candidates_json = "[]"
        self._record.mode = "await_confirm"
        self.db.add(self._record)
        self.db.commit()
        return action

    def confirm(self) -> Optional[Dict]:
        action = self.pending_action
        self.reset()
        return action

    def cancel(self):
        self.reset()

    def reset(self):
        self._record.mode = "idle"
        self._record.action_type = None
        self._record.payload_json = "{}"
        self._record.candidates_json = "[]"
        self.db.add(self._record)
        self.db.commit()

    def clear(self):
        self.reset()
        self._record.step_storage_json = "{}"
        self._record.step_counter = 0
        self.db.add(self._record)
        self.db.commit()

    def next_step(self) -> int:
        self._record.step_counter += 1
        self.db.add(self._record)
        self.db.commit()
        return self._record.step_counter

    def store(self, step_id: int, output: Dict[str, Any]):
        storage = json.loads(self._record.step_storage_json)
        storage[str(step_id)] = output
        self._record.step_storage_json = json.dumps(storage)
        self.db.add(self._record)
        self.db.commit()

    def reset_steps(self):
        self._record.step_storage_json = "{}"
        self._record.step_counter = 0
        self.db.add(self._record)
        self.db.commit()