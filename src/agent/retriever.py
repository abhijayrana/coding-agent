"""Code retrieval for context building."""

import subprocess
from pathlib import Path
from typing import Any


class Retriever:
    """Retrieve relevant code context from the repository."""

    def __init__(self, repo_root: Path, max_files: int = 16, max_bytes: int = 20000) -> None:
        self.repo_root = repo_root
        self.max_files = max_files
        self.max_bytes = max_bytes

    def retrieve(self, query: str) -> list[dict[str, Any]]:
        """Retrieve relevant files based on query."""
        snippets = []
        seen_paths = set()

        # 1. Get important files (manifests, main files)
        for snippet in self._get_manifest_files():
            if snippet["path"] not in seen_paths:
                snippets.append(snippet)
                seen_paths.add(snippet["path"])

        # 2. Extract and retrieve explicitly mentioned files
        mentioned_files = self._extract_filenames(query)
        for filepath in mentioned_files:
            if filepath not in seen_paths:
                snippet = self.get_file_context(filepath)
                if snippet["content"]:  # Only add if file exists
                    snippets.append(snippet)
                    seen_paths.add(filepath)

        # 3. Extract key entities (nouns) for better search
        entities = self._extract_entities(query)

        # 4. Search for entity terms in code
        for entity in entities:
            for snippet in self._search_code(entity):
                if snippet["path"] not in seen_paths:
                    snippets.append(snippet)
                    seen_paths.add(snippet["path"])

        # 5. For small repos, include all Python files if we have room
        if len(snippets) < self.max_files:
            for snippet in self._get_all_source_files():
                if snippet["path"] not in seen_paths and len(snippets) < self.max_files:
                    snippets.append(snippet)
                    seen_paths.add(snippet["path"])

        # Limit to max_files
        return snippets[: self.max_files]

    def _get_manifest_files(self) -> list[dict[str, Any]]:
        """Get important manifest and configuration files."""
        important_files = [
            "pyproject.toml",
            "setup.py",
            "requirements.txt",
            "package.json",
            "README.md",
            "Makefile",
        ]

        snippets = []
        for filename in important_files:
            filepath = self.repo_root / filename
            if filepath.exists():
                try:
                    content = filepath.read_text(encoding="utf-8")
                    if len(content.encode("utf-8")) <= self.max_bytes:
                        snippets.append({"path": filename, "content": content, "lines": None})
                except Exception:
                    pass

        return snippets

    def _search_code(self, query: str) -> list[dict[str, Any]]:
        """Search code using ripgrep."""
        snippets = []

        try:
            # Use ripgrep to find files containing query terms
            result = subprocess.run(
                ["rg", "-l", "--max-count", "5", query],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                files = result.stdout.strip().split("\n")
                for filepath_str in files[: self.max_files]:
                    try:
                        filepath = self.repo_root / filepath_str
                        if filepath.exists():
                            content = filepath.read_text(encoding="utf-8")

                            # Truncate if too large
                            if len(content.encode("utf-8")) > self.max_bytes:
                                content = content[: self.max_bytes] + "\n... (truncated)"

                            snippets.append(
                                {"path": filepath_str, "content": content, "lines": None}
                            )
                    except Exception:
                        pass

        except (subprocess.TimeoutExpired, FileNotFoundError):
            # Fallback: just return manifest files
            pass

        return snippets

    def get_file_context(self, filepath: str) -> dict[str, Any]:
        """Get specific file context."""
        full_path = self.repo_root / filepath
        if not full_path.exists():
            return {"path": filepath, "content": "", "lines": None}

        try:
            content = full_path.read_text(encoding="utf-8")
            if len(content.encode("utf-8")) > self.max_bytes:
                content = content[: self.max_bytes] + "\n... (truncated)"

            return {"path": filepath, "content": content, "lines": None}
        except Exception:
            return {"path": filepath, "content": "", "lines": None}

    def _extract_filenames(self, query: str) -> list[str]:
        """Extract explicit filenames from query."""
        import re

        # Match common file patterns: word.extension
        # Examples: calculator.py, main.js, README.md, config.yaml
        pattern = r'\b[\w\-]+\.(py|js|ts|jsx|tsx|md|txt|json|yaml|yml|toml|cfg|ini|sh|bash)\b'
        matches = re.findall(pattern, query, re.IGNORECASE)

        # Return unique filenames (the full match including extension)
        filenames = []
        for match in re.finditer(pattern, query, re.IGNORECASE):
            filenames.append(match.group(0))

        return list(set(filenames))

    def _extract_entities(self, query: str) -> list[str]:
        """Extract key entities (nouns) from query for search."""
        import re

        # Remove common stop words
        stop_words = {
            'create', 'write', 'add', 'update', 'delete', 'remove', 'edit', 'modify',
            'the', 'a', 'an', 'this', 'that', 'these', 'those', 'is', 'are', 'was', 'were',
            'for', 'with', 'about', 'what', 'how', 'why', 'when', 'where', 'can', 'could',
            'should', 'would', 'file', 'files', 'code', 'make', 'help', 'please'
        }

        # Extract words (alphanumeric, at least 3 chars)
        words = re.findall(r'\b[a-zA-Z]{3,}\b', query.lower())

        # Filter out stop words and keep meaningful entities
        entities = [w for w in words if w not in stop_words]

        # Return unique entities (first 5 to avoid too many searches)
        return list(set(entities))[:5]

    def _get_all_source_files(self) -> list[dict[str, Any]]:
        """Get all source files in the repo (for small repos)."""
        snippets = []
        source_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.go', '.rs', '.c', '.cpp', '.h'}

        try:
            for filepath in self.repo_root.rglob('*'):
                if filepath.is_file() and filepath.suffix in source_extensions:
                    # Skip hidden, cache, and node_modules
                    if any(part.startswith('.') for part in filepath.parts):
                        continue
                    if '__pycache__' in str(filepath) or 'node_modules' in str(filepath):
                        continue

                    try:
                        content = filepath.read_text(encoding='utf-8')
                        if len(content.encode('utf-8')) <= self.max_bytes:
                            relative_path = str(filepath.relative_to(self.repo_root))
                            snippets.append({
                                'path': relative_path,
                                'content': content,
                                'lines': None
                            })
                    except Exception:
                        pass

        except Exception:
            pass

        return snippets
