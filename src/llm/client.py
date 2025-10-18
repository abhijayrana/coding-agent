"""LLM client for planning and reflection."""

import json
import os
from typing import Any, Literal

from anthropic import Anthropic
from openai import OpenAI

from .schemas import Intent, Plan, ReflectionResult


class LLMClient:
    """Wrapper for LLM providers with structured output."""

    def __init__(
        self,
        provider: Literal["anthropic", "openai"] = "anthropic",
        model: str = "claude-3-5-sonnet-20241022",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout: int = 60,
    ) -> None:
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

        if provider == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not set")
            self.client = Anthropic(api_key=api_key, timeout=timeout)
        elif provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not set")
            self.client = OpenAI(api_key=api_key, timeout=timeout)
        else:
            raise ValueError(f"Unknown provider: {provider}")

    def plan(
        self, messages: list[dict[str, str]], context_snippets: list[dict[str, Any]]
    ) -> Plan:
        """Generate a plan from user messages and code context."""
        system_prompt = self._get_planner_system_prompt()
        context_str = self._format_context(context_snippets)

        # Add context to messages
        full_messages = [
            {
                "role": "user",
                "content": f"<repository_context>\n{context_str}\n</repository_context>",
            }
        ] + messages

        if self.provider == "anthropic":
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=system_prompt,
                messages=full_messages,
            )
            content = response.content[0].text
        else:  # openai
            full_messages_with_system = [{"role": "system", "content": system_prompt}] + full_messages

            # GPT-5 has different parameter requirements
            is_gpt5 = self.model.startswith("gpt-5")
            token_param = "max_completion_tokens" if is_gpt5 else "max_tokens"

            params = {
                "model": self.model,
                token_param: self.max_tokens,
                "messages": full_messages_with_system,
                "response_format": {"type": "json_object"},
            }

            # GPT-5 only supports temperature=1 (default)
            if not is_gpt5:
                params["temperature"] = self.temperature

            response = self.client.chat.completions.create(**params)
            content = response.choices[0].message.content

        # Parse JSON response
        try:
            plan_dict = json.loads(content)
            return Plan.model_validate(plan_dict)
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"Failed to parse plan from LLM: {e}\n\nContent: {content}")

    def reflect(
        self,
        original_plan: Plan,
        verification_result: dict[str, Any],
        diffs: list[str],
    ) -> ReflectionResult:
        """Reflect on failures and generate a fix plan."""
        system_prompt = self._get_reflector_system_prompt()

        reflection_prompt = f"""
The following plan was executed:
{original_plan.model_dump_json(indent=2)}

The verification failed with these results:
{json.dumps(verification_result, indent=2)}

These changes were made:
{chr(10).join(diffs)}

Analyze what went wrong and provide a minimal fix plan (1-3 actions maximum).
Output valid JSON matching the ReflectionResult schema.
"""

        messages = [{"role": "user", "content": reflection_prompt}]

        if self.provider == "anthropic":
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=system_prompt,
                messages=messages,
            )
            content = response.content[0].text
        else:  # openai
            messages_with_system = [{"role": "system", "content": system_prompt}] + messages
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=messages_with_system,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content

        try:
            reflection_dict = json.loads(content)
            return ReflectionResult.model_validate(reflection_dict)
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"Failed to parse reflection from LLM: {e}\n\nContent: {content}")

    def classify_intent(self, user_input: str, session_context: str = "") -> Intent:
        """Classify user intent to determine how to handle the request.

        Args:
            user_input: The raw user message
            session_context: Optional context about what's happened in the session

        Returns:
            Intent object with classification and recommended action
        """
        prompt = f"""Classify this user request into one of four categories:

USER REQUEST: "{user_input}"

SESSION CONTEXT: {session_context if session_context else "No prior context"}

CATEGORIES:

1. **function_call** - User wants to execute a SINGLE simple command:
   - commit/save changes to git
   - verify/check/test/lint the code
   - status/show what happened (agent session status, NOT repo contents)
   - repo_summary/show what's in the repository (files, structure, overview)
   - read_file/show contents of a specific file (e.g., "read calculator.py", "show me main.js")
   - quit/exit the session

   Examples:
   - "commit", "try committing again"
   - "verify", "check if it works"
   - "status", "what happened" (session actions)
   - "what's in this repo", "what does this repo have", "show me the files" (repo contents)
   - "read calculator.py", "show me the calculator file", "what's in main.js" (specific file)
   - "quit"

2. **compound_request** - User wants to execute MULTIPLE commands in sequence:
   - Two or more function calls combined with "and", "then", "also"
   - Sequential operations like "verify and commit", "commit then verify"

   Examples: "verify and commit", "commit then check status", "verify, commit, and show status"

   IMPORTANT: Return function_sequence as a list: ["verify", "commit"]

3. **clarification_needed** - Request is ambiguous, incomplete, or contains negations:
   - Could mean multiple things
   - Missing critical information
   - Unclear which action to take
   - Contains negations: "don't", "not", "never"
   - Questions asking for advice: "should I", "is it okay to"
   - Dangerous operations that need confirmation (delete files, etc.)

   Examples: "fix it" (fix what?), "add that" (add what?), "don't commit" (negation), "should I commit?" (asking advice), "delete main.py" (dangerous)

   IMPORTANT: For dangerous operations requiring confirmation, populate "pending_action" with:
   - type: the action type (e.g., "delete_file", "overwrite_file")
   - Any parameters needed to execute the action (e.g., "file_path": "main.py")

4. **plan_required** - User wants to make changes to the codebase OR execute system/shell commands:
   - Add new features
   - Fix bugs
   - Refactor code
   - Update documentation
   - Install dependencies
   - Execute shell commands to query system info (python version, git status, environment variables, etc.)
   - Run terminal commands (ls, grep, cat, etc.)

   Examples:
   - "add a /health endpoint", "fix the auth bug", "refactor the database layer"
   - "what python version am i using?", "check git status", "list the files", "show environment variables"
   - "run ls -la", "grep for TODO", "cat the config file"

CRITICAL RULES:

A. NEGATIONS (don't, not, never):
   - "don't commit" → clarification_needed (user said NOT to do it!)
   - "not yet" → clarification_needed
   - "never mind" → clarification_needed or quit (depending on context)

B. QUESTIONS vs COMMANDS:
   - "should I commit?" → clarification_needed (asking for advice)
   - "can we verify?" → function_call (polite command form)
   - "did you commit?" → status (past tense = check history)
   - "is it working?" → could be status OR verify (use context to decide)

C. CONTEXT WEIGHTING:
   - Weight session context HEAVILY for ambiguous single-word commands
   - After many fs_write actions: "try again" likely means → commit
   - After shell_run (tests): "check" likely means → status (see test results)
   - After verification failures: "fix it" → clarification (what specifically failed?)

D. COMPOUND DETECTION:
   - Look for: "and", "then", "also", commas between actions
   - "verify and commit" → compound_request with ["verify", "commit"]
   - "commit then verify" → compound_request with ["commit", "verify"]

E. REPO vs SESSION STATUS vs READ FILE vs SYSTEM QUERIES:
   - "what happened" → status (session actions)
   - "what's in this repo" → repo_summary (repository structure)
   - "what does this repo have" → repo_summary (NOT status!)
   - "show me the files" → repo_summary (list of files)

   - "read calculator.py" → read_file (show file contents!)
   - "show me calculator.py" → read_file (show file contents!)
   - "what's in calculator.py" → read_file (NOT repo_summary!)
   - "open the calculator file" → read_file
   - "display main.js" → read_file

   - "what python version am i using?" → plan_required (needs shell: python --version)
   - "check git status" → plan_required (needs shell: git status)
   - "list the files" → plan_required (needs shell: ls)
   - "show environment variables" → plan_required (needs shell: env)

   KEY DISTINCTION:
   - SPECIFIC filename mentioned (calculator.py, main.js) → read_file
   - General query (this repo, the files, the project) → repo_summary
   - Agent actions/history (what happened, what did you do) → status
   - System/environment queries (python version, git status, env vars) → plan_required

Return valid JSON matching this schema:
{{
  "type": "function_call" | "compound_request" | "clarification_needed" | "plan_required",
  "confidence": 0.0-1.0,
  "function_name": "commit" | "verify" | "status" | "repo_summary" | "read_file" | "quit" (only if type=function_call),
  "file_path": "path/to/file.py" (only if function_name=read_file, the file to read),
  "function_sequence": ["verify", "commit"] (only if type=compound_request, ordered list),
  "clarification_question": "your question" (only if type=clarification_needed),
  "pending_action": {{"type": "delete_file", "file_path": "main.py"}} (only if type=clarification_needed AND it's a dangerous action awaiting confirmation),
  "reasoning": "brief explanation of your classification"
}}"""

        messages = [{"role": "user", "content": prompt}]

        if self.provider == "anthropic":
            response = self.client.messages.create(
                model=self.model,
                max_tokens=512,  # Intent classification is cheap
                temperature=0.0,  # Deterministic classification
                system=self._get_intent_classifier_system_prompt(),
                messages=messages,
            )
            content = response.content[0].text
        else:
            # OpenAI
            messages_with_system = [
                {"role": "system", "content": self._get_intent_classifier_system_prompt()},
                *messages,
            ]

            is_gpt5 = self.model.startswith("gpt-5")
            token_param = "max_completion_tokens" if is_gpt5 else "max_tokens"

            params = {
                "model": self.model,
                token_param: 512,
                "messages": messages_with_system,
                "response_format": {"type": "json_object"},
            }

            # GPT-5 only supports temperature=1
            if not is_gpt5:
                params["temperature"] = 0.0

            response = self.client.chat.completions.create(**params)
            content = response.choices[0].message.content

        try:
            intent_dict = json.loads(content)
            return Intent.model_validate(intent_dict)
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"Failed to parse intent from LLM: {e}\n\nContent: {content}")

    def _get_intent_classifier_system_prompt(self) -> str:
        """Get the system prompt for intent classification."""
        return """You are an intent classifier for a coding agent.

Your job is to quickly determine what the user wants:
- Single function call? (commit, verify, status, quit)
- Multiple functions? (compound request)
- Need more info? (ambiguous, negations, advice questions)
- Complex task? (requires code planning)

CRITICAL:
- Detect negations ("don't", "not") → clarification_needed
- Distinguish advice questions ("should I?") from polite commands ("can we?")
- Weight session context HEAVILY for ambiguous words
- Detect compound requests ("and", "then", "also")

Be decisive. Output ONLY valid JSON. No markdown blocks."""

    def _get_planner_system_prompt(self) -> str:
        """Get the system prompt for planning."""
        return """You are a coding agent that plans changes to local repositories.

Your job is to create a detailed plan with specific actions. Follow these rules:

1. **Path Safety**: All file paths must be relative to the repository root. Never use absolute paths or path traversal (../).

2. **Minimal Diffs**: Make the smallest possible changes. Prefer targeted edits over rewriting entire files.

3. **Risk Assessment**: Assign each action a risk_score:
   - 0.0-0.3: Safe (reading, small edits, adding tests)
   - 0.4-0.6: Moderate (refactoring, dependency changes)
   - 0.7-1.0: Dangerous (deleting files, running shell commands, modifying configs)

4. **Action Types**:
   - fs_write: Create new file or overwrite existing. Args: {path: str, content: str}

   - fs_insert_lines: (PREFERRED for adding new code) Insert content at specific line. Args: {path: str, line_number: int, content: str, operation: str}
     DETERMINISTIC: No text matching required. Just specify line number.
     operation: "after" (insert after line), "before" (insert before line), "replace" (replace line)
     Example - Adding modulo to calculator.py (file has 14 lines):
     {
       "path": "calculator.py",
       "line_number": 14,
       "operation": "after",
       "content": "\n    def modulo(self, a, b):\n        if b == 0:\n            raise ValueError('Modulo by zero is not allowed')\n        return a % b"
     }

   - fs_edit: Modify existing code (use only when changing existing code, NOT for adding new code). Args: {path: str, old_text: str, new_text: str}
     CRITICAL: old_text must be EXACTLY copied from the file context. Include ALL characters (quotes, spaces, newlines).
     For ADDING new code, prefer fs_insert_lines instead.

   - fs_delete: Delete file. Args: {path: str}
   - shell_run: Execute shell command. Args: {command: str}
   - deps_install: Install dependencies. Args: {language: str, packages: list[str]}

5. **Output Format**: Return valid JSON matching the Plan schema:
{
  "goal": "user's goal",
  "steps": [
    {
      "type": "fs_write",
      "rationale": "why this is needed",
      "args": {"path": "...", "content": "..."},
      "target_files": ["file.py"],
      "risk_score": 0.2
    }
  ],
  "expected_outcome": "what should work after",
  "rollback_hint": "how to undo if needed"
}

6. **Best Practices**:
   - Explain each action's rationale clearly
   - Keep edits small and focused
   - Add tests when adding features
   - Respect existing code style
   - Create parent directories if needed

Output ONLY valid JSON. Do not include markdown code blocks or explanations."""

    def _get_reflector_system_prompt(self) -> str:
        """Get the system prompt for reflection."""
        return """You are a debugging agent that fixes code issues.

Analyze the failure and create a minimal fix plan. Follow these rules:

1. **Root Cause**: Identify the exact problem (syntax error, wrong logic, missing import, etc.)

2. **Minimal Fix**: Create a plan with 1-3 actions maximum. Fix only what's broken.

3. **CRITICAL for fs_edit**: The old_text MUST be EXACTLY copied from the file. Match quotes, spaces, and newlines character-for-character. If text doesn't match exactly, the edit will fail.

4. **Output Format**: Return valid JSON matching the ReflectionResult schema:
{
  "analysis": "The issue is X because Y",
  "fix_plan": {
    "goal": "Fix X",
    "steps": [
      {
        "type": "fs_edit",
        "rationale": "correct the import",
        "args": {"path": "...", "old_text": "...", "new_text": "..."},
        "target_files": ["file.py"],
        "risk_score": 0.1
      }
    ],
    "expected_outcome": "tests pass",
    "rollback_hint": null
  }
}

Output ONLY valid JSON. Do not include markdown code blocks or explanations."""

    def _format_context(self, snippets: list[dict[str, Any]]) -> str:
        """Format code context snippets for the LLM."""
        formatted = []
        for snippet in snippets:
            path = snippet.get("path", "unknown")
            content = snippet.get("content", "")
            lines = snippet.get("lines", None)
            if lines:
                formatted.append(f"--- {path} (lines {lines[0]}-{lines[1]}) ---\n{content}")
            else:
                formatted.append(f"--- {path} ---\n{content}")
        return "\n\n".join(formatted)
