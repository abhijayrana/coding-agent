"""Shell command execution with safety checks."""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ShellResult:
    """Result of a shell command execution."""

    success: bool
    command: str
    stdout: str
    stderr: str
    exit_code: int
    message: str


class ShellTool:
    """Safe shell command execution with allowlist."""

    def __init__(
        self, repo_root: Path, allowlist: list[str], max_timeout: int = 120
    ) -> None:
        self.repo_root = repo_root
        self.allowlist = allowlist
        self.max_timeout = max_timeout

    def run(self, command: str, timeout: Optional[int] = None) -> ShellResult:
        """Execute a shell command safely."""
        # Validate command
        validation_error = self._validate_command(command)
        if validation_error:
            return ShellResult(
                success=False,
                command=command,
                stdout="",
                stderr="",
                exit_code=-1,
                message=f"Command rejected: {validation_error}",
            )

        # Use provided timeout or default
        actual_timeout = timeout if timeout is not None else self.max_timeout

        try:
            # Run command in repo root
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=actual_timeout,
            )

            success = result.returncode == 0
            message = "Command executed successfully" if success else "Command failed"

            return ShellResult(
                success=success,
                command=command,
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                message=message,
            )

        except subprocess.TimeoutExpired:
            return ShellResult(
                success=False,
                command=command,
                stdout="",
                stderr="",
                exit_code=-1,
                message=f"Command timed out after {actual_timeout}s",
            )
        except Exception as e:
            return ShellResult(
                success=False,
                command=command,
                stdout="",
                stderr="",
                exit_code=-1,
                message=f"Error executing command: {e}",
            )

    def _validate_command(self, command: str) -> Optional[str]:
        """Validate command is safe. Returns error message if invalid."""
        # Check if command starts with an allowed executable
        command_stripped = command.strip()
        first_word = command_stripped.split()[0] if command_stripped else ""

        # Handle commands with flags or arguments
        base_command = first_word.split("/")[-1]  # Handle paths like /usr/bin/python

        if base_command not in self.allowlist:
            return f"Command '{base_command}' not in allowlist"

        # Check for dangerous patterns
        dangerous_patterns = [
            (r"\brm\s+-rf\s+/", "Dangerous recursive delete"),
            (r"curl.*\|.*bash", "Piping curl to bash"),
            (r"wget.*\|.*bash", "Piping wget to bash"),
            (r"\bsudo\b", "Sudo not allowed"),
            (r">\s*/dev/", "Writing to /dev/ not allowed"),
        ]

        for pattern, reason in dangerous_patterns:
            if re.search(pattern, command):
                return reason

        return None
