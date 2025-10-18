"""Dependency management tools."""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass
class DepsResult:
    """Result of a dependency operation."""

    success: bool
    message: str
    stdout: str
    stderr: str


class DependencyTool:
    """Manage dependencies for Python and Node.js projects."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def install(
        self, language: Literal["python", "node"], packages: list[str]
    ) -> DepsResult:
        """Install packages."""
        if language == "python":
            return self._install_python(packages)
        elif language == "node":
            return self._install_node(packages)
        else:
            return DepsResult(
                success=False,
                message=f"Unknown language: {language}",
                stdout="",
                stderr="",
            )

    def _install_python(self, packages: list[str]) -> DepsResult:
        """Install Python packages."""
        try:
            # Try uv first if available
            try:
                cmd = ["uv", "pip", "install"] + packages
                result = subprocess.run(
                    cmd,
                    cwd=self.repo_root,
                    capture_output=True,
                    text=True,
                    timeout=300,
                    check=False  # Don't raise on non-zero exit
                )

                if result.returncode == 0:
                    return DepsResult(
                        success=True,
                        message=f"Installed Python packages with uv: {', '.join(packages)}",
                        stdout=result.stdout,
                        stderr=result.stderr,
                    )
            except FileNotFoundError:
                # uv not installed, fall through to pip
                pass

            # Fallback to pip (either uv not found or uv failed)
            # Use sys.executable -m pip to ensure we use the correct Python environment
            cmd = [sys.executable, "-m", "pip", "install"] + packages
            result = subprocess.run(
                cmd, cwd=self.repo_root, capture_output=True, text=True, timeout=300
            )

            success = result.returncode == 0
            message = f"Installed Python packages with pip: {', '.join(packages)}" if success else "Installation failed"

            return DepsResult(
                success=success,
                message=message,
                stdout=result.stdout,
                stderr=result.stderr,
            )

        except Exception as e:
            return DepsResult(
                success=False, message=f"Error installing Python packages: {e}", stdout="", stderr=""
            )

    def _install_node(self, packages: list[str]) -> DepsResult:
        """Install Node.js packages."""
        try:
            # Check for package manager
            if (self.repo_root / "pnpm-lock.yaml").exists():
                cmd = ["pnpm", "add"] + packages
            elif (self.repo_root / "yarn.lock").exists():
                cmd = ["yarn", "add"] + packages
            else:
                cmd = ["npm", "install"] + packages

            result = subprocess.run(
                cmd, cwd=self.repo_root, capture_output=True, text=True, timeout=300
            )

            success = result.returncode == 0
            message = f"Installed Node packages: {', '.join(packages)}" if success else "Installation failed"

            return DepsResult(
                success=success,
                message=message,
                stdout=result.stdout,
                stderr=result.stderr,
            )

        except Exception as e:
            return DepsResult(
                success=False, message=f"Error installing Node packages: {e}", stdout="", stderr=""
            )
