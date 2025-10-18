"""CLI interface using Typer and Rich."""

import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax
from rich.table import Table

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent import AgentConfig
from agent.core import CodingAgent

app = typer.Typer(help="Coding Agent - AI-powered code editing assistant")
console = Console()


@app.command()
def init(
    repo_path: Path = typer.Option(Path.cwd(), "--path", "-p", help="Repository path")
) -> None:
    """Initialize coding agent in a repository."""
    console.print("[bold cyan]Initializing coding agent...[/bold cyan]")

    # Check if already initialized
    config_path = repo_path / "agent.yaml"
    if config_path.exists():
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        return

    # Detect language
    config = AgentConfig()
    language = config.detect_language(repo_path)

    if language:
        console.print(f"[green]Detected {language} project[/green]")
    else:
        console.print("[yellow]Could not detect project language[/yellow]")

    # Create config from example
    example_path = repo_path / "agent.config.example.yaml"
    if example_path.exists():
        import shutil

        shutil.copy(example_path, config_path)
    else:
        config.save(config_path)

    console.print(f"[green]Created config at {config_path}[/green]")
    console.print("\n[bold]Next steps:[/bold]")
    console.print("1. Set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env")
    console.print("2. Review and customize agent.yaml")
    console.print("3. Run: coding-agent chat")


@app.command()
def chat(
    repo_path: Path = typer.Option(Path.cwd(), "--path", "-p", help="Repository path")
) -> None:
    """Start interactive chat session."""
    console.print(Panel.fit("[bold cyan]Coding Agent Chat[/bold cyan]", border_style="cyan"))

    # Load environment
    from dotenv import load_dotenv

    load_dotenv()

    # Check API keys
    if not os.getenv("ANTHROPIC_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        console.print("[red]Error: No API keys found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY[/red]")
        raise typer.Exit(1)

    # Initialize agent
    try:
        agent = CodingAgent(repo_path)
        console.print(f"[green]Initialized in {repo_path}[/green]\n")
    except Exception as e:
        console.print(f"[red]Error initializing agent: {e}[/red]")
        raise typer.Exit(1)

    # Chat loop
    console.print("[dim]The agent runs in iterative mode by default (observe → replan loop)[/dim]")
    console.print("[dim]Commands: /verify, /commit, /status, /quit[/dim]\n")

    while True:
        try:
            user_input = Prompt.ask("[bold cyan]You[/bold cyan]")

            if not user_input.strip():
                continue

            # Check if there's a pending confirmation
            if agent.state.pending_confirmation:
                confirmation = agent.state.pending_confirmation

                # Check if user is confirming
                user_lower = user_input.strip().lower()
                if user_lower in ['yes', 'y', 'confirm', 'ok', 'sure']:
                    console.print(f"[green]Confirmed: {confirmation['action']}[/green]\n")

                    # Execute the pending action
                    if confirmation['type'] == 'delete_file':
                        # Execute file deletion
                        result = agent.fs_tool.delete(confirmation['file_path'])
                        if result.success:
                            console.print(f"[green]✓ Deleted {confirmation['file_path']}[/green]")
                        else:
                            console.print(f"[red]✗ Failed to delete: {result.message}[/red]")

                    # Clear pending confirmation
                    agent.state.pending_confirmation = None
                    continue

                elif user_lower in ['no', 'n', 'cancel', 'abort']:
                    console.print(f"[yellow]Cancelled: {confirmation['action']}[/yellow]\n")
                    agent.state.pending_confirmation = None
                    continue
                else:
                    # Not a clear yes/no, treat as new request and clear confirmation
                    console.print(f"[yellow]Previous confirmation cancelled. Processing new request...[/yellow]\n")
                    agent.state.pending_confirmation = None
                    # Fall through to process new request

            # Handle commands
            if user_input.startswith("/"):
                if user_input == "/quit" or user_input == "/exit":
                    console.print("[yellow]Goodbye![/yellow]")
                    break
                elif user_input == "/status":
                    show_status(agent)
                    continue
                elif user_input == "/verify":
                    run_verification(agent)
                    continue
                elif user_input == "/commit":
                    commit_changes(agent)
                    continue
                else:
                    console.print(f"[red]Unknown command: {user_input}[/red]")
                    continue

            # Classify user intent using LLM
            console.print("[dim]Understanding your request...[/dim]")
            try:
                # Build session context from recent actions
                session_context = ""
                if agent.state.executed_actions:
                    recent_actions = agent.state.executed_actions[-3:]  # Last 3 actions
                    session_context = "Recent actions: " + ", ".join(
                        f"{a['type']}" for a in recent_actions
                    )

                intent = agent.llm_client.classify_intent(user_input, session_context)
                console.print(f"[dim]{intent.reasoning}[/dim]\n")

                # Handle based on intent type
                if intent.type == "function_call":
                    # Direct function execution (function_name is a FunctionType enum)
                    if intent.function_name.value == "commit":
                        commit_changes(agent)
                        continue
                    elif intent.function_name.value == "verify":
                        run_verification(agent)
                        continue
                    elif intent.function_name.value == "status":
                        show_status(agent)
                        continue
                    elif intent.function_name.value == "repo_summary":
                        show_repo_summary(agent)
                        continue
                    elif intent.function_name.value == "read_file":
                        if intent.file_path:
                            show_file(agent, intent.file_path)
                        else:
                            console.print("[yellow]⚠ No file path specified[/yellow]")
                        continue
                    elif intent.function_name.value == "quit":
                        console.print("\n[yellow]Goodbye![/yellow]")
                        break

                elif intent.type == "compound_request":
                    # Execute multiple functions in sequence
                    console.print(f"[cyan]Executing {len(intent.function_sequence)} actions...[/cyan]\n")
                    for i, func in enumerate(intent.function_sequence, 1):
                        console.print(f"[dim]{i}. {func.value}[/dim]")
                        if func.value == "commit":
                            commit_changes(agent)
                        elif func.value == "verify":
                            run_verification(agent)
                        elif func.value == "status":
                            show_status(agent)
                        elif func.value == "repo_summary":
                            show_repo_summary(agent)
                        elif func.value == "read_file":
                            if intent.file_path:
                                show_file(agent, intent.file_path)
                            else:
                                console.print("[yellow]⚠ read_file in compound request requires file_path[/yellow]")
                    console.print()
                    continue

                elif intent.type == "clarification_needed":
                    # Ask for clarification and save pending action
                    console.print(f"[yellow]❓ {intent.clarification_question}[/yellow]\n")

                    # Save what we're asking about for next turn
                    if intent.pending_action:
                        agent.state.pending_confirmation = {
                            'action': user_input,  # Original user request
                            'question': intent.clarification_question,
                            **intent.pending_action  # Include type, file_path, etc.
                        }

                    continue

                # If plan_required, fall through to planning below

            except Exception as e:
                console.print(f"[yellow]⚠ Intent classification failed: {e}[/yellow]")
                console.print("[dim]Falling back to planning...[/dim]\n")

            # Execute with agent loop (iterative mode)
            console.print("\n[bold yellow]Starting agent loop...[/bold yellow]")
            console.print("[dim]The agent will plan → execute → observe → replan iteratively[/dim]\n")
            try:
                # Run agent loop
                results = agent.agent_loop(user_input, max_iterations=10, steps_per_iteration=3)

                # Show results
                show_agent_loop_results(results)

                if results["success"]:
                    console.print("\n[bold green]✓ Agent loop completed successfully[/bold green]")

                    if results["self_corrections"] > 0:
                        console.print(f"[cyan]💡 Agent self-corrected {results['self_corrections']} time(s)[/cyan]")

                    # Run verification
                    console.print("\n[bold yellow]Running verification...[/bold yellow]")
                    verify_result = agent.verify_changes()
                    show_verification_results(verify_result)

                    if verify_result["status"] == "pass":
                        console.print("\n[bold green]✓ All checks passed[/bold green]")

                        if Confirm.ask("Commit changes?"):
                            commit_changes(agent)
                    else:
                        console.print("\n[bold red]✗ Verification failed[/bold red]")

                        if Confirm.ask("Attempt to fix issues automatically?"):
                            console.print("\n[bold yellow]Reflecting and fixing...[/bold yellow]")
                            fix_result = agent.reflect_and_fix()

                            if fix_result["success"]:
                                console.print(
                                    f"[bold green]✓ Issues fixed in {fix_result['attempts']} attempt(s)[/bold green]"
                                )

                                if Confirm.ask("Commit changes?"):
                                    commit_changes(agent)
                            else:
                                console.print(f"[bold red]✗ {fix_result['message']}[/bold red]")
                else:
                    console.print("\n[bold red]✗ Plan execution failed[/bold red]")

            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                import traceback

                console.print(f"[dim]{traceback.format_exc()}[/dim]")

            console.print()

        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted[/yellow]")
            if Confirm.ask("Quit?"):
                break
            console.print()


def show_plan(plan) -> None:
    """Display plan in a nice format."""
    console.print(f"\n[bold]Goal:[/bold] {plan.goal}")
    console.print(f"[bold]Expected outcome:[/bold] {plan.expected_outcome}\n")

    table = Table(title="Plan Steps", show_header=True, header_style="bold magenta")
    table.add_column("#", justify="right", style="cyan", width=3)
    table.add_column("Action", style="yellow", width=15)
    table.add_column("Rationale", style="white", width=50)
    table.add_column("Risk", justify="right", style="red", width=6)

    for i, step in enumerate(plan.steps, 1):
        risk_color = "green" if step.risk_score < 0.3 else "yellow" if step.risk_score < 0.7 else "red"
        table.add_row(
            str(i),
            step.type.value,
            step.rationale[:47] + "..." if len(step.rationale) > 50 else step.rationale,
            f"[{risk_color}]{step.risk_score:.2f}[/{risk_color}]",
        )

    console.print(table)


def show_execution_results(results: dict) -> None:
    """Display execution results."""
    for step in results["steps"]:
        status = "✓" if step["success"] else "✗"
        color = "green" if step["success"] else "red"
        console.print(f"[{color}]{status} Step {step['step']}: {step['message']}[/{color}]")

        if step["diff"]:
            console.print(Syntax(step["diff"], "diff", theme="monokai", line_numbers=False))


def show_agent_loop_results(results: dict) -> None:
    """Display agent loop results with iterations and self-corrections."""
    console.print(f"\n[bold cyan]Agent Loop Summary[/bold cyan]")
    console.print(f"  Iterations: {results['iterations']}")
    console.print(f"  Steps executed: {results['steps_executed']}")
    console.print(f"  Self-corrections: {results['self_corrections']}")

    # Show each step with observation details
    console.print(f"\n[bold]Steps:[/bold]")
    for i, (step, obs) in enumerate(zip(results["steps"], results["observations"]), 1):
        status = "✓" if obs["success"] else "✗"
        color = "green" if obs["success"] else "red"
        console.print(f"[{color}]{status} Step {i}: {step['action_type']}[/{color}]")
        console.print(f"   {step['message']}")

        if not obs["success"] and obs.get("error_type"):
            console.print(f"   [yellow]Error type: {obs['error_type']}[/yellow]")

        if obs.get("affected_files"):
            console.print(f"   [dim]Files: {', '.join(obs['affected_files'])}[/dim]")

        if step.get("diff"):
            console.print(f"   [dim]Diff: {len(step['diff'])} bytes[/dim]")

    console.print()


def show_verification_results(results: dict) -> None:
    """Display verification results."""
    status_color = "green" if results["status"] == "pass" else "red"
    console.print(f"\n[{status_color}]Status: {results['status'].upper()}[/{status_color}]")
    console.print(f"Summary: {results['summary']}")

    if results["lint_errors"]:
        console.print("\n[red]Lint errors:[/red]")
        for error in results["lint_errors"][:5]:
            console.print(f"  • {error}")

    if results["failing_tests"]:
        console.print("\n[red]Failing tests:[/red]")
        for test in results["failing_tests"][:5]:
            console.print(f"  • {test}")


def show_status(agent: CodingAgent) -> None:
    """Display agent status."""
    status = agent.get_status()

    table = Table(title="Agent Status", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Session ID", status["session"]["session_id"])
    table.add_row("Has Plan", "✓" if status["has_plan"] else "✗")
    if status["plan_goal"]:
        table.add_row("Current Goal", status["plan_goal"])
    table.add_row("Actions Executed", str(status["actions_executed"]))
    table.add_row("Diffs Generated", str(status["diffs_count"]))

    console.print(table)


def show_repo_summary(agent: CodingAgent) -> None:
    """Display repository summary with file structure and overview."""
    import subprocess
    from pathlib import Path

    repo_root = agent.repo_root

    console.print(f"\n[bold cyan]📁 Repository: {repo_root.name}[/bold cyan]")
    console.print(f"[dim]Path: {repo_root}[/dim]\n")

    # Count files by type
    file_counts = {}
    total_files = 0
    total_lines = 0

    for file_path in repo_root.rglob("*"):
        if file_path.is_file():
            # Skip hidden and generated files
            if any(part.startswith('.') for part in file_path.parts):
                continue
            if '__pycache__' in str(file_path) or 'node_modules' in str(file_path):
                continue

            total_files += 1
            suffix = file_path.suffix or 'no extension'
            file_counts[suffix] = file_counts.get(suffix, 0) + 1

            # Count lines (simple, just for stats)
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    total_lines += sum(1 for _ in f)
            except:
                pass

    # Show statistics
    stats_table = Table(title="Repository Statistics", show_header=False)
    stats_table.add_column("Metric", style="cyan")
    stats_table.add_column("Value", style="white")

    stats_table.add_row("Total Files", str(total_files))
    stats_table.add_row("Total Lines", f"{total_lines:,}")

    # Top file types
    top_types = sorted(file_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    for suffix, count in top_types:
        stats_table.add_row(f"  {suffix} files", str(count))

    console.print(stats_table)
    console.print()

    # Show directory structure (using tree if available, otherwise simple listing)
    console.print("[bold]📂 Directory Structure:[/bold]\n")

    try:
        # Try to use tree command
        result = subprocess.run(
            ['tree', '-L', '2', '-I', '__pycache__|node_modules|.git|*.pyc|venv', str(repo_root)],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            console.print(result.stdout)
        else:
            raise Exception("tree command failed")
    except:
        # Fallback: simple directory listing
        def show_tree(path: Path, prefix: str = "", max_depth: int = 2, current_depth: int = 0):
            if current_depth >= max_depth:
                return

            try:
                items = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
                # Filter out hidden and common excludes
                items = [
                    p for p in items
                    if not p.name.startswith('.')
                    and p.name not in ['__pycache__', 'node_modules', 'venv']
                ]

                for i, item in enumerate(items):
                    is_last = i == len(items) - 1
                    current_prefix = "└── " if is_last else "├── "
                    console.print(f"{prefix}{current_prefix}{item.name}{'/' if item.is_dir() else ''}")

                    if item.is_dir():
                        next_prefix = prefix + ("    " if is_last else "│   ")
                        show_tree(item, next_prefix, max_depth, current_depth + 1)
            except PermissionError:
                pass

        console.print(f"{repo_root.name}/")
        show_tree(repo_root)

    # Show key files if they exist
    key_files = [
        'README.md', 'requirements.txt', 'pyproject.toml', 'package.json',
        'Dockerfile', 'Makefile', '.gitignore', 'setup.py'
    ]

    found_key_files = [f for f in key_files if (repo_root / f).exists()]

    if found_key_files:
        console.print(f"\n[bold]📄 Key Files:[/bold]")
        for filename in found_key_files:
            console.print(f"  • {filename}")

    console.print()


def run_verification(agent: CodingAgent) -> None:
    """Run verification checks."""
    console.print("[yellow]Running verification...[/yellow]")
    results = agent.verify_changes()
    show_verification_results(results)


def commit_changes(agent: CodingAgent) -> None:
    """Commit changes to git."""
    message = Prompt.ask("Commit message (optional)", default="")
    result = agent.commit_changes(message if message else None)

    if result["success"]:
        console.print(f"[green]✓ Committed: {result['sha']}[/green]")
        console.print(f"[dim]Artifacts saved to .agent_runs/{agent.state.session_id}[/dim]")
    else:
        console.print(f"[red]✗ Commit failed: {result['message']}[/red]")


def show_file(agent: CodingAgent, file_path: str) -> None:
    """Display the contents of a file with syntax highlighting."""
    from pathlib import Path

    try:
        # Resolve the file path
        full_path = agent.repo_root / file_path

        if not full_path.exists():
            console.print(f"[red]✗ File not found: {file_path}[/red]")
            return

        if not full_path.is_file():
            console.print(f"[red]✗ Not a file: {file_path}[/red]")
            return

        # Read the file
        result = agent.fs_tool.read(file_path)

        if not result.success:
            console.print(f"[red]✗ Could not read file: {result.message}[/red]")
            return

        content = result.data

        # Detect language for syntax highlighting
        suffix = full_path.suffix.lstrip('.')
        language_map = {
            'py': 'python',
            'js': 'javascript',
            'ts': 'typescript',
            'jsx': 'jsx',
            'tsx': 'tsx',
            'java': 'java',
            'go': 'go',
            'rs': 'rust',
            'c': 'c',
            'cpp': 'cpp',
            'h': 'c',
            'hpp': 'cpp',
            'md': 'markdown',
            'yaml': 'yaml',
            'yml': 'yaml',
            'json': 'json',
            'html': 'html',
            'css': 'css',
            'sh': 'bash',
            'bash': 'bash',
        }

        lexer = language_map.get(suffix, 'text')

        # Create syntax-highlighted display
        syntax = Syntax(
            content,
            lexer,
            theme="monokai",
            line_numbers=True,
            word_wrap=False,
        )

        # Display in a panel
        console.print(Panel(
            syntax,
            title=f"[bold cyan]{file_path}[/bold cyan]",
            border_style="cyan",
            expand=False,
        ))

        # Show file stats
        lines = content.count('\n') + 1
        size = len(content)
        console.print(f"[dim]{lines} lines, {size} bytes[/dim]\n")

    except Exception as e:
        console.print(f"[red]✗ Error reading file: {e}[/red]")


if __name__ == "__main__":
    app()
