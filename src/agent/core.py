"""Core agent orchestration."""

import time
import uuid
from pathlib import Path
from typing import Optional

from agent import (
    AgentConfig,
    ApprovalSystem,
    Executor,
    Retriever,
    SessionState,
    Verifier,
)
from llm import LLMClient, Plan
from llm.schemas import Action, Observation
from tools import DependencyTool, FileSystemTool, GitTool, ShellTool


class CodingAgent:
    """Main coding agent that orchestrates planning and execution."""

    def __init__(self, repo_root: Path, config: Optional[AgentConfig] = None) -> None:
        self.repo_root = repo_root.resolve()
        self.config = config or AgentConfig.load(repo_root / "agent.yaml")

        # Initialize components
        self.llm_client = LLMClient(
            provider=self.config.llm.provider,
            model=self.config.llm.model,
            temperature=self.config.llm.temperature,
            max_tokens=self.config.llm.max_output_tokens,
            timeout=self.config.llm.timeout,
        )

        self.fs_tool = FileSystemTool(
            repo_root=self.repo_root,
            max_file_size=self.config.safety.max_file_size_bytes,
        )

        self.git_tool = GitTool(repo_root=self.repo_root)

        self.shell_tool = ShellTool(
            repo_root=self.repo_root,
            allowlist=self.config.safety.shell_command_allowlist,
            max_timeout=self.config.safety.max_shell_timeout,
        )

        self.deps_tool = DependencyTool(repo_root=self.repo_root)

        self.executor = Executor(
            repo_root=self.repo_root,
            fs_tool=self.fs_tool,
            git_tool=self.git_tool,
            shell_tool=self.shell_tool,
            deps_tool=self.deps_tool,
        )

        self.retriever = Retriever(
            repo_root=self.repo_root,
            max_files=self.config.retrieval.max_files,
            max_bytes=self.config.retrieval.max_bytes_per_file,
        )

        self.verifier = Verifier(repo_root=self.repo_root, config=self.config)

        self.approval_system = ApprovalSystem(
            auto_approve_max=self.config.risk.auto_approve_score_max,
            delete_file_max=self.config.risk.delete_file_max_count,
            dangerous_patterns=self.config.risk.require_approval_patterns,
        )

        # Session state
        session_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
        self.state = SessionState(session_id=session_id, repo_root=self.repo_root)

    def plan(self, user_message: str) -> Plan:
        """Generate a plan from user message."""
        # Add user message to state
        self.state.add_message("user", user_message)

        # Retrieve context
        context = self.retriever.retrieve(user_message)

        # Generate plan
        plan = self.llm_client.plan(self.state.messages, context)

        # Save plan to state
        self.state.current_plan = plan

        return plan

    def execute_plan(self, plan: Plan, dry_run: bool = False) -> dict:
        """Execute all steps in a plan."""
        results = {"success": True, "steps": [], "diffs": []}

        for i, action in enumerate(plan.steps):
            result = self.executor.execute(action, dry_run=dry_run)

            step_result = {
                "step": i + 1,
                "action_type": action.type.value,
                "success": result.success,
                "message": result.message,
                "diff": result.diff,
            }

            results["steps"].append(step_result)

            # Track action in state
            self.state.add_action_result(action.type.value, step_result)

            # Track diffs
            if result.diff:
                self.state.add_diff(result.diff)
                results["diffs"].append(result.diff)

            # Stop on failure
            if not result.success:
                results["success"] = False
                break

        return results

    def verify_changes(self) -> dict:
        """Run verification checks."""
        verification_result = self.verifier.verify()
        self.state.verification_results.append(verification_result)
        return verification_result

    def reflect_and_fix(self, max_retries: int = 2) -> dict:
        """Reflect on failures and attempt fixes."""
        if not self.state.current_plan:
            return {"success": False, "message": "No plan to reflect on"}

        for attempt in range(max_retries):
            # Verify current state
            verify_result = self.verify_changes()

            if verify_result["status"] == "pass":
                return {"success": True, "message": "Verification passed", "attempts": attempt + 1}

            # Get reflection from LLM
            reflection = self.llm_client.reflect(
                self.state.current_plan, verify_result, self.state.diffs
            )

            # Execute fix plan
            fix_results = self.execute_plan(reflection.fix_plan)

            if not fix_results["success"]:
                return {
                    "success": False,
                    "message": f"Fix attempt {attempt + 1} failed",
                    "attempts": attempt + 1,
                }

        return {
            "success": False,
            "message": f"Max retries ({max_retries}) exceeded",
            "attempts": max_retries,
        }

    def commit_changes(self, message: Optional[str] = None) -> dict:
        """Commit changes to git."""
        if message is None and self.state.current_plan:
            message = f"{self.state.current_plan.goal}\n\nGenerated by coding-agent"

        result = self.git_tool.commit(message or "Agent changes")

        if result.success:
            self.state.save_artifacts()

        return {"success": result.success, "message": result.message, "sha": result.data}

    def get_status(self) -> dict:
        """Get current session status."""
        return {
            "session": self.state.get_summary(),
            "has_plan": self.state.current_plan is not None,
            "plan_goal": self.state.current_plan.goal if self.state.current_plan else None,
            "actions_executed": len(self.state.executed_actions),
            "diffs_count": len(self.state.diffs),
        }

    def observe(self, action: Action, result: dict) -> Observation:
        """Analyze the result of an action execution."""
        # Extract error type from message if failed
        error_type = None
        if not result.success:
            message_lower = result.message.lower()
            if "import" in message_lower:
                error_type = "ImportError"
            elif "syntax" in message_lower:
                error_type = "SyntaxError"
            elif "not found" in message_lower or "does not exist" in message_lower:
                error_type = "FileNotFoundError"
            elif "permission" in message_lower:
                error_type = "PermissionError"
            else:
                error_type = "UnknownError"

        # Extract affected files
        affected_files = []
        if action.type.value.startswith("fs_"):
            path = action.args.get("path")
            if path:
                affected_files.append(path)

        # Determine if can retry
        can_retry = True
        if error_type in ["PermissionError"]:
            can_retry = False

        # Create context updates
        context_update = {}
        if result.success:
            if action.type.value == "fs_write":
                context_update["file_created"] = action.args.get("path")
            elif action.type.value in ["fs_edit", "fs_insert_lines"]:
                context_update["file_modified"] = action.args.get("path")
            elif action.type.value == "fs_delete":
                context_update["file_deleted"] = action.args.get("path")

        return Observation(
            action_type=action.type.value,
            success=result.success,
            message=result.message,
            error_type=error_type,
            affected_files=affected_files,
            diff=result.diff if result.success else None,
            can_retry=can_retry,
            context_update=context_update,
        )

    def plan_next_steps(self, context: list[dict], max_steps: int = 3) -> Plan:
        """Plan just the next 1-3 steps based on current context."""
        # Build prompt for incremental planning
        completed_actions = [
            f"- {action['type']}: {action['result'].get('message', 'done')}"
            for action in self.state.executed_actions[-5:]  # Last 5 actions
        ]

        # Add incremental planning context to messages
        incremental_prompt = f"""
Current task: {self.state.current_plan.goal if self.state.current_plan else 'Continue working'}

Actions completed so far:
{chr(10).join(completed_actions) if completed_actions else '(none yet)'}

Based on what's been done, plan the next {max_steps} steps ONLY.
Consider:
- What has already succeeded
- What the current state of the codebase is
- What's the most important next action

Return a plan with AT MOST {max_steps} steps.
"""
        self.state.add_message("system", incremental_prompt)

        # Generate incremental plan
        plan = self.llm_client.plan(self.state.messages, context)

        # Limit to max_steps
        if len(plan.steps) > max_steps:
            plan.steps = plan.steps[:max_steps]

        return plan

    def agent_loop(
        self, user_message: str, max_iterations: int = 10, steps_per_iteration: int = 3
    ) -> dict:
        """Execute task with iterative observe-replan loop (agent mode).

        Args:
            user_message: The user's task request
            max_iterations: Maximum number of plan-execute cycles
            steps_per_iteration: How many steps to plan/execute per iteration

        Returns:
            dict with success status, iterations taken, and results
        """
        # Initialize
        self.state.add_message("user", user_message)
        context = self.retriever.retrieve(user_message)

        # Generate initial plan (to understand the goal)
        initial_plan = self.llm_client.plan(self.state.messages, context)
        self.state.current_plan = initial_plan

        results = {
            "success": True,
            "iterations": 0,
            "steps_executed": 0,
            "steps": [],
            "observations": [],
            "self_corrections": 0,
        }

        for iteration in range(max_iterations):
            results["iterations"] = iteration + 1

            # Plan next steps (incremental)
            if iteration == 0:
                # Use initial plan's first N steps
                next_plan = initial_plan
                actions_to_execute = initial_plan.steps[:steps_per_iteration]
            else:
                # Replan based on observations
                next_plan = self.plan_next_steps(context, max_steps=steps_per_iteration)
                actions_to_execute = next_plan.steps

            if not actions_to_execute:
                # No more actions planned, task might be complete
                break

            # Execute actions and observe results
            for action in actions_to_execute:
                # Execute action
                exec_result = self.executor.execute(action)

                # Observe what happened
                observation = self.observe(action, exec_result)

                # Track results
                step_result = {
                    "step": results["steps_executed"] + 1,
                    "action_type": action.type.value,
                    "success": observation.success,
                    "message": observation.message,
                    "diff": observation.diff,
                }

                results["steps"].append(step_result)
                results["observations"].append(observation.dict())
                results["steps_executed"] += 1

                # Track in state
                self.state.add_action_result(action.type.value, step_result)
                if observation.diff:
                    self.state.add_diff(observation.diff)

                # Handle failure with automatic reflection
                if not observation.success:
                    if observation.can_retry:
                        # Attempt automatic fix
                        try:
                            reflection = self.llm_client.reflect(
                                self.state.current_plan,
                                {"status": "fail", "message": observation.message},
                                self.state.diffs,
                            )

                            # Try to execute fix
                            if reflection.fix_plan and reflection.fix_plan.steps:
                                results["self_corrections"] += 1

                                for fix_action in reflection.fix_plan.steps[:2]:  # Max 2 fix steps
                                    fix_result = self.executor.execute(fix_action)

                                    if fix_result.success:
                                        # Fix worked! Update context
                                        fix_observation = self.observe(fix_action, fix_result)
                                        results["observations"].append(fix_observation.dict())

                                        # Update context with fix
                                        if fix_observation.context_update:
                                            context.append({
                                                "path": fix_observation.affected_files[0]
                                                if fix_observation.affected_files
                                                else "fix",
                                                "content": f"Fixed: {fix_observation.message}",
                                            })
                                        break
                                    else:
                                        # Fix failed, stop trying
                                        results["success"] = False
                                        return results
                        except Exception:
                            # Reflection failed, stop
                            results["success"] = False
                            return results
                    else:
                        # Can't retry, stop
                        results["success"] = False
                        return results

                # Update context with successful changes
                if observation.success and observation.context_update:
                    # Add to context for next iteration
                    if observation.affected_files:
                        # Re-read the modified file to get latest content
                        for file_path in observation.affected_files:
                            try:
                                file_content = self.fs_tool.read(file_path)
                                if file_content.success and file_content.data:
                                    # Update context with new file content
                                    existing_idx = None
                                    for idx, ctx in enumerate(context):
                                        if ctx.get("path") == file_path:
                                            existing_idx = idx
                                            break

                                    if existing_idx is not None:
                                        context[existing_idx]["content"] = file_content.data
                                    else:
                                        context.append(
                                            {"path": file_path, "content": file_content.data}
                                        )
                            except Exception:
                                pass  # Skip if can't read file

            # Check if task is complete (simple heuristic)
            verify_result = self.verify_changes()
            if verify_result["status"] == "pass":
                # Task complete!
                results["success"] = True
                break

        return results
