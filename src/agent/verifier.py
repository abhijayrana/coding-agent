"""Code verification (lint/type/test)."""

import subprocess
from pathlib import Path
from typing import Any, Literal, Optional

from agent.config import AgentConfig


class Verifier:
    """Run linters, type checkers, and tests."""

    def __init__(self, repo_root: Path, config: AgentConfig) -> None:
        self.repo_root = repo_root
        self.config = config
        self.language = config.detect_language(repo_root)

    def verify(self) -> dict[str, Any]:
        """Run all verification checks."""
        results = {
            "status": "pass",
            "lint_errors": [],
            "type_errors": [],
            "failing_tests": [],
            "summary": "",
        }

        # Run linters
        if self.language == "python":
            lint_results = self._run_python_linters()
            results["lint_errors"] = lint_results
        elif self.language == "node":
            lint_results = self._run_node_linters()
            results["lint_errors"] = lint_results

        # Run tests
        test_results = self._run_tests()
        if not test_results["success"]:
            results["failing_tests"] = test_results["output"]

        # Determine overall status
        if results["lint_errors"] or results["type_errors"] or results["failing_tests"]:
            results["status"] = "fail"
            error_count = (
                len(results["lint_errors"])
                + len(results["type_errors"])
                + len(results["failing_tests"])
            )
            results["summary"] = f"Found {error_count} issues"
        else:
            results["summary"] = "All checks passed"

        return results

    def _run_python_linters(self) -> list[str]:
        """Run Python linters."""
        errors = []

        for linter_cmd in self.config.linters.python:
            result = self._run_command(linter_cmd)
            if not result["success"] and result["stderr"]:
                errors.append(f"{linter_cmd}: {result['stderr'][:500]}")

        return errors

    def _run_node_linters(self) -> list[str]:
        """Run Node.js linters."""
        errors = []

        for linter_cmd in self.config.linters.node:
            result = self._run_command(linter_cmd)
            if not result["success"] and result["stderr"]:
                errors.append(f"{linter_cmd}: {result['stderr'][:500]}")

        return errors

    def _run_tests(self) -> dict[str, Any]:
        """Run tests based on detected language."""
        if self.language == "python":
            cmd = self.config.tests.python
        elif self.language == "node":
            cmd = self.config.tests.node
        else:
            return {"success": True, "output": []}

        result = self._run_command(cmd)
        return {
            "success": result["success"],
            "output": [result["stdout"][:500]] if not result["success"] else [],
        }

    def _run_command(self, command: str) -> dict[str, Any]:
        """Run a command and return result."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=self.config.safety.max_shell_timeout,
            )

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "stdout": "",
                "stderr": "Command timed out",
                "exit_code": -1,
            }
        except Exception as e:
            return {"success": False, "stdout": "", "stderr": str(e), "exit_code": -1}
