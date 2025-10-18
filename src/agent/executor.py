"""Plan executor with dry-run capability."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm.schemas import Action, ActionType
from tools import DependencyTool, FileSystemTool, GitTool, ShellTool


@dataclass
class ExecutionResult:
    """Result of executing an action."""

    success: bool
    message: str
    diff: str = ""
    data: Any = None


class Executor:
    """Execute actions from plans."""

    def __init__(
        self,
        repo_root: Path,
        fs_tool: FileSystemTool,
        git_tool: GitTool,
        shell_tool: ShellTool,
        deps_tool: DependencyTool,
    ) -> None:
        self.repo_root = repo_root
        self.fs_tool = fs_tool
        self.git_tool = git_tool
        self.shell_tool = shell_tool
        self.deps_tool = deps_tool

    def execute(self, action: Action, dry_run: bool = False) -> ExecutionResult:
        """Execute a single action."""
        if dry_run:
            return self._dry_run(action)

        # Execute based on action type
        if action.type == ActionType.FS_WRITE:
            return self._execute_fs_write(action)
        elif action.type == ActionType.FS_EDIT:
            return self._execute_fs_edit(action)
        elif action.type == ActionType.FS_INSERT_LINES:
            return self._execute_fs_insert_lines(action)
        elif action.type == ActionType.FS_DELETE:
            return self._execute_fs_delete(action)
        elif action.type == ActionType.SHELL_RUN:
            return self._execute_shell_run(action)
        elif action.type == ActionType.DEPS_INSTALL:
            return self._execute_deps_install(action)
        elif action.type == ActionType.GIT_CHECKOUT:
            return self._execute_git_checkout(action)
        else:
            return ExecutionResult(
                success=False, message=f"Unknown action type: {action.type}"
            )

    def _dry_run(self, action: Action) -> ExecutionResult:
        """Simulate action execution."""
        return ExecutionResult(
            success=True,
            message=f"[DRY RUN] Would execute {action.type.value}: {action.rationale}",
            data=action.args,
        )

    def _execute_fs_write(self, action: Action) -> ExecutionResult:
        """Execute file write."""
        path = action.args.get("path")
        content = action.args.get("content")

        if not path or content is None:
            return ExecutionResult(success=False, message="Missing path or content")

        result = self.fs_tool.write(path, content)
        return ExecutionResult(
            success=result.success,
            message=result.message,
            diff=result.diff or "",
            data={"path": path},
        )

    def _execute_fs_edit(self, action: Action) -> ExecutionResult:
        """Execute file edit."""
        path = action.args.get("path")
        old_text = action.args.get("old_text")
        new_text = action.args.get("new_text")

        if not path or old_text is None or new_text is None:
            return ExecutionResult(success=False, message="Missing path, old_text, or new_text")

        result = self.fs_tool.edit(path, old_text, new_text)
        return ExecutionResult(
            success=result.success,
            message=result.message,
            diff=result.diff or "",
            data={"path": path},
        )

    def _execute_fs_insert_lines(self, action: Action) -> ExecutionResult:
        """Execute line-based file insertion (deterministic)."""
        path = action.args.get("path")
        line_number = action.args.get("line_number")
        content = action.args.get("content")
        operation = action.args.get("operation", "after")

        if not path or line_number is None or content is None:
            return ExecutionResult(success=False, message="Missing path, line_number, or content")

        result = self.fs_tool.insert_lines(path, line_number, content, operation)
        return ExecutionResult(
            success=result.success,
            message=result.message,
            diff=result.diff or "",
            data={"path": path, "line_number": line_number},
        )

    def _execute_fs_delete(self, action: Action) -> ExecutionResult:
        """Execute file deletion."""
        path = action.args.get("path")

        if not path:
            return ExecutionResult(success=False, message="Missing path")

        result = self.fs_tool.delete(path)
        return ExecutionResult(
            success=result.success, message=result.message, data={"path": path}
        )

    def _execute_shell_run(self, action: Action) -> ExecutionResult:
        """Execute shell command."""
        command = action.args.get("command")
        timeout = action.args.get("timeout")

        if not command:
            return ExecutionResult(success=False, message="Missing command")

        result = self.shell_tool.run(command, timeout)
        return ExecutionResult(
            success=result.success,
            message=result.message,
            data={"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.exit_code},
        )

    def _execute_deps_install(self, action: Action) -> ExecutionResult:
        """Execute dependency installation."""
        language = action.args.get("language")
        packages = action.args.get("packages")

        if not language or not packages:
            return ExecutionResult(success=False, message="Missing language or packages")

        result = self.deps_tool.install(language, packages)
        return ExecutionResult(
            success=result.success,
            message=result.message,
            data={"stdout": result.stdout, "stderr": result.stderr},
        )

    def _execute_git_checkout(self, action: Action) -> ExecutionResult:
        """Execute git branch checkout."""
        branch = action.args.get("branch")
        create = action.args.get("create", False)

        if not branch:
            return ExecutionResult(success=False, message="Missing branch name")

        result = self.git_tool.checkout_branch(branch, create)
        return ExecutionResult(success=result.success, message=result.message, data={"branch": branch})
