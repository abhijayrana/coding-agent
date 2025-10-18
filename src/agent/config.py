"""Configuration management."""

import os
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    provider: Literal["anthropic", "openai"] = "anthropic"
    model: str = "claude-3-5-sonnet-20241022"
    temperature: float = 0.1
    max_output_tokens: int = 4096
    timeout: int = 60


class RetrievalConfig(BaseModel):
    """Code retrieval configuration."""

    max_files: int = 16
    max_bytes_per_file: int = 20000


class TestConfig(BaseModel):
    """Test command configuration."""

    python: str = "pytest -q"
    node: str = "npm test --silent"


class LinterConfig(BaseModel):
    """Linter configuration."""

    python: list[str] = Field(default_factory=lambda: ["ruff check", "mypy"])
    node: list[str] = Field(default_factory=lambda: ["eslint", "tsc --noEmit"])


class RiskConfig(BaseModel):
    """Risk assessment configuration."""

    auto_approve_score_max: float = 0.3
    delete_file_max_count: int = 3
    require_approval_patterns: list[str] = Field(
        default_factory=lambda: ["rm ", "sudo", "curl.*bash", "wget.*bash"]
    )


class SafetyConfig(BaseModel):
    """Safety configuration."""

    path_jail_enabled: bool = True
    shell_command_allowlist: list[str] = Field(
        default_factory=lambda: [
            "pytest",
            "python",
            "python3",
            "node",
            "npm",
            "pnpm",
            "yarn",
            "ruff",
            "mypy",
            "eslint",
            "tsc",
            "make",
            "uv",
            "pip",
            "git",
        ]
    )
    max_shell_timeout: int = 120
    max_file_size_bytes: int = 1048576


class AgentConfig(BaseModel):
    """Complete agent configuration."""

    repo_root: str = "."
    llm: LLMConfig = Field(default_factory=LLMConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    tests: TestConfig = Field(default_factory=TestConfig)
    linters: LinterConfig = Field(default_factory=LinterConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AgentConfig":
        """Load configuration from file."""
        if path is None:
            path = Path("agent.yaml")

        if not path.exists():
            # Return default config
            return cls()

        with path.open() as f:
            data = yaml.safe_load(f)

        return cls.model_validate(data)

    def save(self, path: Optional[Path] = None) -> None:
        """Save configuration to file."""
        if path is None:
            path = Path("agent.yaml")

        with path.open("w") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False)

    def detect_language(self, repo_root: Path) -> Optional[Literal["python", "node"]]:
        """Detect primary language of repository."""
        if (repo_root / "pyproject.toml").exists() or (repo_root / "setup.py").exists():
            return "python"
        if (repo_root / "package.json").exists():
            return "node"
        return None
