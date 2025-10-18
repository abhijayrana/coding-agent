"""File system operations with path jail and safety checks."""

import difflib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class FileOperation:
    """Result of a file operation."""

    success: bool
    message: str
    diff: Optional[str] = None
    path: Optional[str] = None
    data: Optional[str] = None  # For read operations


class FileSystemTool:
    """Safe file system operations within a repository."""

    def __init__(self, repo_root: Path, max_file_size: int = 1048576) -> None:
        self.repo_root = repo_root.resolve()
        self.max_file_size = max_file_size
        self.trash_dir = self.repo_root / ".agent_trash"

    def _validate_path(self, path: str) -> Path:
        """Validate path is within repo root and resolve it."""
        # Convert to Path and resolve
        full_path = (self.repo_root / path).resolve()

        # Check it's within repo_root (path jail)
        try:
            full_path.relative_to(self.repo_root)
        except ValueError:
            raise ValueError(f"Path {path} is outside repository root")

        # Reject absolute paths
        if Path(path).is_absolute():
            raise ValueError(f"Absolute paths not allowed: {path}")

        return full_path

    def read(self, path: str) -> FileOperation:
        """Read a file."""
        try:
            full_path = self._validate_path(path)

            if not full_path.exists():
                return FileOperation(
                    success=False, message=f"File not found: {path}", path=str(full_path)
                )

            if not full_path.is_file():
                return FileOperation(
                    success=False, message=f"Not a file: {path}", path=str(full_path)
                )

            if full_path.stat().st_size > self.max_file_size:
                return FileOperation(
                    success=False,
                    message=f"File too large: {path} (max {self.max_file_size} bytes)",
                    path=str(full_path),
                )

            content = full_path.read_text(encoding="utf-8")
            return FileOperation(
                success=True, message=f"Read {len(content)} bytes", path=str(full_path), data=content
            )

        except Exception as e:
            return FileOperation(success=False, message=f"Error reading {path}: {e}")

    def write(self, path: str, content: str) -> FileOperation:
        """Write content to a file (create or overwrite)."""
        try:
            full_path = self._validate_path(path)

            # Check size limit
            if len(content.encode("utf-8")) > self.max_file_size:
                return FileOperation(
                    success=False, message=f"Content too large for {path}", path=str(full_path)
                )

            # Create parent directories
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # Get old content for diff
            old_content = ""
            if full_path.exists():
                old_content = full_path.read_text(encoding="utf-8")

            # Write file
            full_path.write_text(content, encoding="utf-8")

            # Generate diff
            diff = self._generate_diff(old_content, content, str(path))

            action = "Updated" if old_content else "Created"
            return FileOperation(
                success=True,
                message=f"{action} {path} ({len(content)} bytes)",
                diff=diff,
                path=str(full_path),
            )

        except Exception as e:
            return FileOperation(success=False, message=f"Error writing {path}: {e}")

    def edit(self, path: str, old_text: str, new_text: str) -> FileOperation:
        """Edit a file by replacing old_text with new_text."""
        try:
            full_path = self._validate_path(path)

            if not full_path.exists():
                return FileOperation(
                    success=False, message=f"File not found: {path}", path=str(full_path)
                )

            # Read current content
            content = full_path.read_text(encoding="utf-8")

            # Check if old_text exists
            if old_text not in content:
                return FileOperation(
                    success=False,
                    message=f"Text not found in {path}. Cannot apply edit.",
                    path=str(full_path),
                )

            # Replace text
            new_content = content.replace(old_text, new_text, 1)

            # Write back
            full_path.write_text(new_content, encoding="utf-8")

            # Generate diff
            diff = self._generate_diff(content, new_content, str(path))

            return FileOperation(
                success=True, message=f"Edited {path}", diff=diff, path=str(full_path)
            )

        except Exception as e:
            return FileOperation(success=False, message=f"Error editing {path}: {e}")

    def insert_lines(self, path: str, line_number: int, content: str, operation: str = "after") -> FileOperation:
        """Insert content at a specific line number (deterministic editing).

        Args:
            path: File path
            line_number: Line number (1-indexed)
            content: Content to insert
            operation: "after" (insert after line) or "before" (insert before line) or "replace" (replace line)
        """
        try:
            full_path = self._validate_path(path)

            if not full_path.exists():
                return FileOperation(
                    success=False, message=f"File not found: {path}", path=str(full_path)
                )

            # Read current content
            lines = full_path.read_text(encoding="utf-8").splitlines(keepends=True)

            # Handle case where file doesn't end with newline
            if lines and not lines[-1].endswith('\n'):
                lines[-1] += '\n'

            # Validate line number
            if line_number < 1 or line_number > len(lines) + 1:
                return FileOperation(
                    success=False,
                    message=f"Line number {line_number} out of range (file has {len(lines)} lines)",
                    path=str(full_path),
                )

            old_content = ''.join(lines)

            # Ensure content ends with newline if not empty
            if content and not content.endswith('\n'):
                content += '\n'

            # Perform operation
            if operation == "after":
                # Insert after line_number
                lines.insert(line_number, content)
            elif operation == "before":
                # Insert before line_number (so at line_number - 1 in 0-indexed)
                lines.insert(line_number - 1, content)
            elif operation == "replace":
                # Replace the line at line_number
                lines[line_number - 1] = content
            else:
                return FileOperation(
                    success=False,
                    message=f"Invalid operation: {operation}. Must be 'after', 'before', or 'replace'",
                    path=str(full_path),
                )

            new_content = ''.join(lines)

            # Write back
            full_path.write_text(new_content, encoding="utf-8")

            # Generate diff
            diff = self._generate_diff(old_content, new_content, str(path))

            return FileOperation(
                success=True,
                message=f"Inserted at line {line_number} in {path}",
                diff=diff,
                path=str(full_path)
            )

        except Exception as e:
            return FileOperation(success=False, message=f"Error inserting in {path}: {e}")

    def delete(self, path: str) -> FileOperation:
        """Delete a file (move to trash for safety)."""
        try:
            full_path = self._validate_path(path)

            if not full_path.exists():
                return FileOperation(
                    success=False, message=f"File not found: {path}", path=str(full_path)
                )

            # Create trash directory
            self.trash_dir.mkdir(exist_ok=True)

            # Move to trash with timestamp
            import time

            timestamp = int(time.time())
            trash_path = self.trash_dir / f"{timestamp}_{full_path.name}"
            shutil.move(str(full_path), str(trash_path))

            return FileOperation(
                success=True,
                message=f"Deleted {path} (moved to {trash_path})",
                path=str(full_path),
            )

        except Exception as e:
            return FileOperation(success=False, message=f"Error deleting {path}: {e}")

    def list_directory(self, path: str = ".") -> FileOperation:
        """List files in a directory."""
        try:
            full_path = self._validate_path(path)

            if not full_path.exists():
                return FileOperation(
                    success=False, message=f"Directory not found: {path}", path=str(full_path)
                )

            if not full_path.is_dir():
                return FileOperation(
                    success=False, message=f"Not a directory: {path}", path=str(full_path)
                )

            items = sorted([item.name for item in full_path.iterdir()])
            return FileOperation(
                success=True, message=f"Found {len(items)} items", path=str(full_path)
            )

        except Exception as e:
            return FileOperation(success=False, message=f"Error listing {path}: {e}")

    def _generate_diff(self, old_content: str, new_content: str, filename: str) -> str:
        """Generate a unified diff."""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff = difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{filename}", tofile=f"b/{filename}")

        return "".join(diff)
