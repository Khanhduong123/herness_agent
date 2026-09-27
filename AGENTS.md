# AGENTS.md: Rules and Architecture Guidelines for AI Agents

> [!NOTE]
> This file mirrors [Agent.md](file:///d:/herness_agent/Agent.md) to ensure full compatibility with standard workspace rule scanners, Antigravity IDE, and Herdr workspaces.

## 1. System Architecture: Central Orchestrator & Workers

This repository uses a **Central Orchestrator Pattern**:
- **Orchestrator (`orchestrator`)**: Plans, coordinates DAG tasks, routes context, monitors status, and verifies completion. **IMPORTANT NOTE:** Only read/apply skills specifically needed based on user requests, do not blindly read all skills. **CRITICAL RULE:** The Orchestrator MUST NEVER write, modify, or edit code files directly. It must ONLY: 1) Generate Sub-Specs and save them to `.ai/plan/[task_id].md`, 2) Wait for User approval, 3) Create a git worktree (`git worktree add agent/[task_id]`), 4) Create and focus a visible Herdr workspace using `herdr workspace create --cwd $(pwd)/agent/[task_id] --focus`, 5) **DO NOT run `agy` in the background**. Launch the agent interactively: `herdr agent start worker_[task_id] --kind agy --pane <pane_id>`. 6) Send instructions to the agent's input using `herdr agent prompt worker_[task_id] "..."`. **MANDATORY CHECK:** The Orchestrator MUST check if the sub-agent CLI actually ran and MUST wait to receive a completion signal/status from the sub-agent before proceeding or returning results. Do not return results immediately after sending the prompt.
- **Researcher (`researcher`)**: Explores codebase, dependencies, and requirements.
- **Coder / Specialist Agent (`coder`, `agent-backend`, `agent-frontend`, etc.)**: Implements code, adheres to PEP 8, Black, typing, and architectural specs. **Expert Rule:** When delegating a task, the Orchestrator should dynamically suggest and configure the sub-agent as a specialized domain expert (e.g., suggesting an `agent-backend` for API tasks). The sub-agent must adopt the persona of an expert dedicated strictly to that task's domain.
- **Tester (`tester`)**: Writes and runs `pytest` tests; validates 100% pass rate.
- **Reviewer (`reviewer`)**: Conducts code review and compliance checks.

## 2. Environment & Tooling Standards

- **Conda Environment**: Always use the **`pytorch`** environment:
  ```powershell
  conda run -n pytorch <command>
  ```
- **Tests**:
  ```powershell
  conda run -n pytorch pytest
  ```
- **Formatting & Style**:
  - Python 3.10+
  - Black line length: 100
  - Complete type hints on all public interfaces (Pydantic v2 schemas)
  - No unused imports or silent exception swallowing

## 3. Git Operations: Direct agy-cli Control Only (No Programmatic Python Git)

- **Separation of Concerns**: Python source code (`src/`) must NEVER call Git programmatically (no `subprocess.run(["git", ...])` or `gitpython`).
- **Direct agy CLI Execution**: All git actions (branching, commits, diff, status, push) are performed directly by `agy` CLI in the terminal under user direction.
- **Branch Protection**: Never commit directly to `main`.
- **Branch Conventions**: Always work on a dedicated branch (`feat/...`, `fix/...`). Current branch: `feat/orchestrator-architecture`.
- **Conventional Commits**: Use `feat:`, `fix:`, `test:`, `docs:`, `refactor:`. Always inspect `git status` and `git diff` before committing.
- **Rule Sync on Main Only**: Standard rules and SDLC skills updates must only be pulled/synced into the `main` branch of working repositories, never into in-flight feature branches. Feature branches subsequently merge from `main`.

## 4. Herdr Setup

- Windows PowerShell install:
  ```powershell
  powershell -ExecutionPolicy Bypass -c "irm https://herdr.dev/install.ps1 | iex"
  ```
- Windows CMD install:
  ```cmd
  curl.exe -fsSLo install.cmd https://herdr.dev/install.cmd && install.cmd && del install.cmd
  ```
- Unix/WSL install:
  ```bash
  curl -fsSL https://herdr.dev/install.sh | sh
  ```

## 5. SDLC Skills Protocol (`.agents/skills/`)

All agents (including the orchestrator and all sub-agents) must strictly adhere to the SDLC skills discovered in `.agents/skills/`. **CRITICAL RULE:** Agents MUST ONLY read and apply the specific skills that are directly relevant to their current assigned task. Do NOT blindly read all skills in the directory.
- **Pre-Task**: `sdlc-pretask-checklist` (clean git tree, branch checkout, requirement breakdown), `sdlc-architecture-planner` (Pydantic models, DAG plan), and `sdlc-subtask-specifier` (formal sub-spec generation: criticality, risk, function signatures, test cases, status).
- **In-Task**: `sdlc-clean-code-standards` (PEP 8, Black 100 cols, isort, flake8) & `sdlc-test-driven-development` (pytest unit & edge tests).
- **Post-Task Quality Gate**: `sdlc-posttask-quality-gate` (100% pytest pass, linters, git diff), `sdlc-security-audit` (secret prevention, input sanitization), `sdlc-conventional-commit` (conventional commits via agy-cli).


See full details in [Agent.md](file:///d:/herness_agent/Agent.md).

## 6. Language & Communication Standards

- **Code, Documentation & Planning**: All generated plans (`plan.md`), technical specifications (`sub-spec`), code, docstrings, and system documentation MUST be written in **English** unless the user explicitly requests otherwise.
- **Communication (Chat)**: The agent should communicate in the user's preferred language (e.g., Vietnamese) when responding in the chat interface.
