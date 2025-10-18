"""Git operations for the agent."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import git


@dataclass
class GitResult:
    """Result of a git operation."""

    success: bool
    message: str
    data: Optional[str] = None


class GitTool:
    """Git operations for version control."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        try:
            self.repo = git.Repo(repo_root)
        except git.InvalidGitRepositoryError:
            # Not a git repo, initialize one
            self.repo = git.Repo.init(repo_root)

    def status(self) -> GitResult:
        """Get git status."""
        try:
            status = self.repo.git.status()
            return GitResult(success=True, message="Got status", data=status)
        except Exception as e:
            return GitResult(success=False, message=f"Error getting status: {e}")

    def diff(self, cached: bool = False) -> GitResult:
        """Get git diff."""
        try:
            if cached:
                diff = self.repo.git.diff("--cached")
            else:
                diff = self.repo.git.diff()
            return GitResult(success=True, message="Got diff", data=diff)
        except Exception as e:
            return GitResult(success=False, message=f"Error getting diff: {e}")

    def diff_branch(self, base_branch: str = "main") -> GitResult:
        """Get diff from base branch to HEAD."""
        try:
            diff = self.repo.git.diff(f"{base_branch}...HEAD")
            return GitResult(success=True, message=f"Got diff from {base_branch}", data=diff)
        except Exception as e:
            return GitResult(success=False, message=f"Error getting diff: {e}")

    def checkout_branch(self, branch_name: str, create: bool = False) -> GitResult:
        """Checkout a branch."""
        try:
            if create:
                self.repo.git.checkout("-b", branch_name)
            else:
                self.repo.git.checkout(branch_name)
            return GitResult(success=True, message=f"Checked out {branch_name}")
        except Exception as e:
            return GitResult(success=False, message=f"Error checking out branch: {e}")

    def commit(self, message: str) -> GitResult:
        """Create a commit with all changes."""
        try:
            # Add all changes
            self.repo.git.add("-A")

            # Check if there are changes to commit
            # Handle empty repos (no HEAD yet)
            try:
                has_head = self.repo.head.is_valid()
            except ValueError:
                has_head = False

            if has_head and not self.repo.index.diff("HEAD"):
                return GitResult(success=False, message="No changes to commit")

            # Commit
            self.repo.index.commit(message)
            commit_sha = self.repo.head.commit.hexsha[:7]

            return GitResult(
                success=True, message=f"Created commit {commit_sha}", data=commit_sha
            )
        except Exception as e:
            return GitResult(success=False, message=f"Error creating commit: {e}")

    def restore(self, path: Optional[str] = None) -> GitResult:
        """Restore files from HEAD."""
        try:
            if path:
                self.repo.git.restore(path)
                return GitResult(success=True, message=f"Restored {path}")
            else:
                self.repo.git.restore(".")
                return GitResult(success=True, message="Restored all files")
        except Exception as e:
            return GitResult(success=False, message=f"Error restoring: {e}")
