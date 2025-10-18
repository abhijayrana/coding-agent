"""Session state management."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from llm.schemas import Plan


@dataclass
class SessionState:
    """State for a single agent session."""

    session_id: str
    repo_root: Path
    created_at: datetime = field(default_factory=datetime.now)
    messages: list[dict[str, str]] = field(default_factory=list)
    current_plan: Optional[Plan] = None
    executed_actions: list[dict[str, Any]] = field(default_factory=list)
    diffs: list[str] = field(default_factory=list)
    verification_results: list[dict[str, Any]] = field(default_factory=list)
    artifacts_dir: Optional[Path] = None
    pending_confirmation: Optional[dict[str, Any]] = None  # Track what needs confirmation

    def __post_init__(self) -> None:
        """Initialize artifacts directory."""
        if self.artifacts_dir is None:
            runs_dir = self.repo_root / ".agent_runs"
            runs_dir.mkdir(exist_ok=True)
            self.artifacts_dir = runs_dir / self.session_id
            self.artifacts_dir.mkdir(exist_ok=True)

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the conversation."""
        self.messages.append({"role": role, "content": content})

    def add_action_result(self, action_type: str, result: dict[str, Any]) -> None:
        """Record an executed action."""
        self.executed_actions.append(
            {"type": action_type, "result": result, "timestamp": datetime.now().isoformat()}
        )

    def add_diff(self, diff: str) -> None:
        """Record a code diff."""
        if diff:
            self.diffs.append(diff)

    def save_artifacts(self) -> None:
        """Save session artifacts to disk."""
        if not self.artifacts_dir:
            return

        # Save plan
        if self.current_plan:
            plan_file = self.artifacts_dir / "plan.json"
            plan_file.write_text(self.current_plan.model_dump_json(indent=2))

        # Save messages
        messages_file = self.artifacts_dir / "messages.json"
        messages_file.write_text(json.dumps(self.messages, indent=2))

        # Save actions
        actions_file = self.artifacts_dir / "actions.jsonl"
        with actions_file.open("w") as f:
            for action in self.executed_actions:
                f.write(json.dumps(action) + "\n")

        # Save diffs
        if self.diffs:
            diffs_file = self.artifacts_dir / "diffs.txt"
            diffs_file.write_text("\n\n=== DIFF SEPARATOR ===\n\n".join(self.diffs))

        # Save verification results
        if self.verification_results:
            verify_file = self.artifacts_dir / "verification.json"
            verify_file.write_text(json.dumps(self.verification_results, indent=2))

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the session."""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "messages_count": len(self.messages),
            "actions_executed": len(self.executed_actions),
            "diffs_generated": len(self.diffs),
            "has_plan": self.current_plan is not None,
        }
