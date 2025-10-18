# Quick Start

## Install

```bash
git clone <repository-url>
cd langchain-takehome
./install.sh
```

This creates a virtual environment and installs the `coding-agent` command.

## Configure

Add your API key:

```bash
# While still in langchain-takehome/
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

Or for OpenAI:

```bash
echo "OPENAI_API_KEY=sk-..." > .env
```

## Use it

Navigate to any project and start the agent:

```bash
cd ~/my-project
source ~/langchain-takehome/venv/bin/activate
coding-agent chat
```

The agent will operate on whatever directory you're in.

## Example session

```
$ cd ~/my-calculator-app
$ source ~/langchain-takehome/venv/bin/activate
$ coding-agent chat

You: add a Calculator class with add and subtract methods
Agent: [creates calculator.py in current directory]

You: verify
Agent: [runs tests]

You: commit
Agent: [commits to git]

You: quit
```

## Commands

- `add X` / `fix Y` / `refactor Z` - Make changes
- `verify` - Run tests
- `commit` - Create git commit
- `status` - See what happened
- `read file.py` - Show file
- `what's in this repo?` - List files
- `quit` - Exit

## Troubleshooting

**API key error:**
Make sure `.env` exists in `langchain-takehome/` with your API key.

**`coding-agent` command not found:**
Make sure you activated the venv: `source ~/langchain-takehome/venv/bin/activate`

**Command blocked:**
Create `agent.yaml` in your project (copy from `~/langchain-takehome/agent.config.example.yaml`):

```yaml
shell:
  allowed_commands:
    - "npm"
    - "pytest"
```

