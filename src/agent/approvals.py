"""Risk assessment and approval system."""

import re
from dataclasses import dataclass
from typing import Optional

from llm.schemas import Action, Plan


@dataclass
class ApprovalDecision:
    """Decision about whether to approve an action/plan."""

    approved: bool
    risk_score: float
    reason: str
    requires_confirmation: bool


class ApprovalSystem:
    """Assess risk and determine if actions need user approval."""

    def __init__(
        self,
        auto_approve_max: float = 0.3,
        delete_file_max: int = 3,
        dangerous_patterns: Optional[list[str]] = None,
    ) -> None:
        self.auto_approve_max = auto_approve_max
        self.delete_file_max = delete_file_max
        self.dangerous_patterns = dangerous_patterns or [
            r"\brm\s+-rf",
            r"\bsudo\b",
            r"curl.*\|.*bash",
            r"wget.*\|.*bash",
        ]

    def assess_plan(self, plan: Plan) -> ApprovalDecision:
        """Assess overall plan risk."""
        if not plan.steps:
            return ApprovalDecision(
                approved=False,
                risk_score=0.0,
                reason="Plan has no steps",
                requires_confirmation=False,
            )

        # Calculate overall risk
        max_risk = max(step.risk_score for step in plan.steps)
        avg_risk = sum(step.risk_score for step in plan.steps) / len(plan.steps)

        # Count deletions
        delete_count = sum(1 for step in plan.steps if step.type == "fs_delete")

        # Check for dangerous shell commands
        has_dangerous_shell = any(
            self._is_dangerous_shell(step) for step in plan.steps if step.type == "shell_run"
        )

        # Determine if approval needed
        reasons = []

        if max_risk > self.auto_approve_max:
            reasons.append(f"High risk action (score: {max_risk:.2f})")

        if delete_count > self.delete_file_max:
            reasons.append(f"Too many file deletions ({delete_count})")

        if has_dangerous_shell:
            reasons.append("Dangerous shell command detected")

        # Auto-approve if no red flags
        if not reasons:
            return ApprovalDecision(
                approved=True,
                risk_score=max_risk,
                reason="Low risk, auto-approved",
                requires_confirmation=False,
            )

        # Require user confirmation
        return ApprovalDecision(
            approved=False,
            risk_score=max_risk,
            reason="; ".join(reasons),
            requires_confirmation=True,
        )

    def assess_action(self, action: Action) -> ApprovalDecision:
        """Assess individual action risk."""
        risk = action.risk_score

        # Check for specific high-risk patterns
        if action.type == "fs_delete":
            return ApprovalDecision(
                approved=risk <= self.auto_approve_max,
                risk_score=risk,
                reason="File deletion",
                requires_confirmation=risk > self.auto_approve_max,
            )

        if action.type == "shell_run":
            command = action.args.get("command", "")
            if self._is_dangerous_shell_cmd(command):
                return ApprovalDecision(
                    approved=False,
                    risk_score=max(risk, 0.8),
                    reason="Dangerous shell command",
                    requires_confirmation=True,
                )

        # Default approval logic
        approved = risk <= self.auto_approve_max
        return ApprovalDecision(
            approved=approved,
            risk_score=risk,
            reason="Standard risk assessment",
            requires_confirmation=not approved,
        )

    def _is_dangerous_shell(self, action: Action) -> bool:
        """Check if action contains dangerous shell command."""
        if action.type != "shell_run":
            return False

        command = action.args.get("command", "")
        return self._is_dangerous_shell_cmd(command)

    def _is_dangerous_shell_cmd(self, command: str) -> bool:
        """Check if shell command matches dangerous patterns."""
        for pattern in self.dangerous_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        return False
