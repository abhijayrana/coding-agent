"""Pydantic schemas for LLM planning and actions."""

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    """Types of actions the agent can perform."""

    FS_WRITE = "fs_write"
    FS_EDIT = "fs_edit"
    FS_INSERT_LINES = "fs_insert_lines"  # Deterministic line-based editing
    FS_DELETE = "fs_delete"
    SHELL_RUN = "shell_run"
    DEPS_INSTALL = "deps_install"
    GIT_CHECKOUT = "git_checkout"


class Action(BaseModel):
    """A single action to be executed by the agent."""

    type: ActionType
    rationale: str = Field(description="Why this action is necessary")
    args: dict[str, Any] = Field(description="Arguments for the action")
    target_files: list[str] = Field(
        default_factory=list, description="Files affected by this action"
    )
    risk_score: float = Field(
        ge=0.0, le=1.0, description="Risk score from 0 (safe) to 1 (dangerous)"
    )


class Plan(BaseModel):
    """A complete plan with multiple steps."""

    goal: str = Field(description="High-level goal the user requested")
    steps: list[Action] = Field(description="Ordered list of actions to execute")
    expected_outcome: str = Field(description="What should happen after executing the plan")
    rollback_hint: Optional[str] = Field(
        default=None, description="How to revert changes if something goes wrong"
    )


class VerificationResult(BaseModel):
    """Result of running verifiers (lint/type/test)."""

    status: str = Field(description="pass or fail")
    lint_errors: list[str] = Field(default_factory=list)
    type_errors: list[str] = Field(default_factory=list)
    failing_tests: list[str] = Field(default_factory=list)
    summary: str = Field(description="Human-readable summary")


class ReflectionResult(BaseModel):
    """Result of reflecting on failures."""

    analysis: str = Field(description="What went wrong and why")
    fix_plan: Plan = Field(description="Plan to fix the issues")


class Observation(BaseModel):
    """Observation of an action's result (for agent loop)."""

    action_type: str = Field(description="Type of action that was executed")
    success: bool = Field(description="Whether the action succeeded")
    message: str = Field(description="Result message")
    error_type: Optional[str] = Field(None, description="Type of error if failed (e.g., 'ImportError', 'SyntaxError')")
    affected_files: list[str] = Field(default_factory=list, description="Files created/modified")
    diff: Optional[str] = Field(None, description="Code diff if applicable")
    can_retry: bool = Field(default=True, description="Whether this action can be retried")
    context_update: dict[str, Any] = Field(default_factory=dict, description="Updates to agent context")


class FunctionType(str, Enum):
    """Types of functions the agent can call directly."""

    COMMIT = "commit"
    VERIFY = "verify"
    STATUS = "status"
    REPO_SUMMARY = "repo_summary"
    READ_FILE = "read_file"
    QUIT = "quit"


class Intent(BaseModel):
    """Classification of user intent."""

    type: Literal["function_call", "compound_request", "clarification_needed", "plan_required"] = Field(
        description="The type of intent detected"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in the classification (0.0 to 1.0)",
    )
    function_name: Optional[FunctionType] = Field(
        default=None, description="If function_call, which function to execute"
    )
    function_sequence: Optional[list[FunctionType]] = Field(
        default=None, description="If compound_request, ordered list of functions to execute"
    )
    file_path: Optional[str] = Field(
        default=None, description="If read_file, which file to read"
    )
    clarification_question: Optional[str] = Field(
        default=None,
        description="If clarification_needed, what question to ask the user",
    )
    pending_action: Optional[dict] = Field(
        default=None,
        description="If clarification_needed, details of the action awaiting confirmation (e.g., {'type': 'delete_file', 'file_path': 'main.py'})",
    )
    reasoning: str = Field(description="Brief explanation of the classification")
