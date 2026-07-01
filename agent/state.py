# agent/state.py

from typing import Dict, Any, List, Optional


class DependencyState:
    """
    Manages step outputs and resolves dependencies between tool calls.

    In finance agent this is used for delete/update flows:
    - Step 1: view_transactions → stores found transactions with IDs
    - Step 2: delete/update → resolves txn_id from step 1 output

    Example:
        >>> state = DependencyState()
        >>> state.store(1, {"data": {"transactions": [...], "selected_id": None}})
        >>> state.set_selected(1, txn_id="aff42989-...")
        >>> state.resolve("txn_id", from_step=1)
        "aff42989-..."
    """

    def __init__(self):
        self._state: Dict[int, Any] = {}
        self._step_counter: int = 0
        self.mode: str = "idle"           # idle | await_select | await_confirm
        self.pending_action: Optional[Dict] = None   # {action, txn_id, description, fields}
        self.candidates: List[Dict] = []  # [{txn_id, description, action_type, fields}]


    def reset_steps(self):
        """Clear step storage — call before starting a new delete/update flow."""
        self._state.clear()
        self._step_counter = 0


    # ── Step Storage ───────────────────────────────────────────────────────────

    def next_step(self) -> int:
        """Auto-increment step counter and return new step ID."""
        self._step_counter += 1
        return self._step_counter

    def store(self, step_id: int, output: Dict[str, Any]):
        """Store output from an executed step.

        Args:
            step_id: Step ID from next_step()
            output:  Tool output dict — must have 'data' key
        """
        self._state[step_id] = output

    def get_step_output(self, step_id: int) -> Optional[Dict[str, Any]]:
        """Get stored output for a step."""
        return self._state.get(step_id)

    def has_step(self, step_id: int) -> bool:
        """Check if step output exists."""
        return step_id in self._state

    # ── Dependency Resolution ──────────────────────────────────────────────────

    def resolve_dependencies(
        self,
        *,
        tool_args: dict,
        dependencies: List[Dict[str, Any]]
    ) -> dict:
        """Resolve dependencies by injecting stored step values into tool args.

        Args:
            tool_args:     Original tool args — None values will be replaced
            dependencies:  List of {from_step, from_field, to_arg} dicts

        Returns:
            Resolved tool args with dependencies filled in

        Example:
            dependencies = [{"from_step": 1, "from_field": "txn_id", "to_arg": "txn_id"}]
        """
        resolved = dict(tool_args)

        for dep in dependencies:
            from_step = dep["from_step"]
            from_field = dep["from_field"]
            to_arg = dep["to_arg"]

            if from_step not in self._state:
                raise KeyError(f"Step {from_step} not executed yet")

            step_output = self._state[from_step]

            # navigate nested fields using dot notation e.g. "data.txn_id"
            value = step_output
            for key in from_field.split("."):
                if isinstance(value, dict):
                    value = value[key]
                else:
                    raise KeyError(f"Cannot navigate to '{from_field}' in step {from_step} output")

            resolved[to_arg] = value

        return resolved

    # ── Confirmation State Machine ─────────────────────────────────────────────

    def set_candidates(self, candidates: List[Dict], action_type: str):
        """Store transaction candidates and enter select mode.

        Args:
            candidates:  List of {txn_id, description, fields} dicts
            action_type: "delete" or "update"
        """
        self.candidates = [
            {**c, "action_type": action_type}
            for c in candidates
        ]
        self.mode = "await_select"

    def select(self, number: int) -> Optional[Dict]:
        """User picked a number — resolve to pending action.

        Args:
            number: 1-based index from user input

        Returns:
            Pending action dict or None if invalid number
        """
        idx = number - 1
        if idx < 0 or idx >= len(self.candidates):
            return None

        chosen = self.candidates[idx]
        self.pending_action = {
            "action_type": chosen["action_type"],
            "txn_id": chosen["txn_id"],
            "description": chosen["description"],
            "fields": chosen.get("fields", {})
        }
        self.candidates = []
        self.mode = "await_confirm"
        return self.pending_action

    def confirm(self) -> Optional[Dict]:
        """User confirmed — return pending action and reset state.

        Returns:
            Completed pending action dict
        """
        action = self.pending_action
        self.reset()
        return action

    def cancel(self):
        """User cancelled — reset to idle."""
        self.reset()

    def reset(self):
        """Reset confirmation state — keep step storage intact."""
        self.mode = "idle"
        self.candidates = []
        self.pending_action = None

    def clear(self):
        """Full reset — clear everything including step storage."""
        self._state.clear()
        self._step_counter = 0
        self.reset()

    def get_all_outputs(self) -> Dict[int, Any]:
        """Return all stored step outputs — for debugging."""
        return dict(self._state)