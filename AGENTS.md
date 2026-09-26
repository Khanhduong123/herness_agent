# AGENTS.md: Rules and Architecture Guidelines for AI Agents

> [!NOTE]
> This file mirrors [Agent.md](file:///d:/herness_agent/Agent.md) to ensure full compatibility with standard workspace rule scanners, Antigravity IDE, and Herdr workspaces.

## 1. System Architecture: Central Orchestrator & Workers

This repository uses a **Central Orchestrator Pattern**:
- **Orchestrator (`orchestrator`)**: Plans, coordinates DAG tasks, routes context, monitors status, and verifies completion. **CRITICAL RULE:** The Orchestrator MUST NEVER write, modify, or edit code files directly. It must ONLY generate Sub-Specs and delegate execution by spawning isolated Sub-Agents (using `invoke_subagent` or Herdr workspaces).
- **Researcher (`researcher`)**: Explores codebase, dependencies, and requirements.
- **Coder (`coder`)**: Implements code, adheres to PEP 8, Black, typing, and architectural specs.
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

All agents must strictly adhere to the SDLC skills discovered in `.agents/skills/`:
- **Pre-Task**: `sdlc-pretask-checklist` (clean git tree, branch checkout, requirement breakdown), `sdlc-architecture-planner` (Pydantic models, DAG plan), and `sdlc-subtask-specifier` (formal sub-spec generation: criticality, risk, function signatures, test cases, status).
- **In-Task**: `sdlc-clean-code-standards` (PEP 8, Black 100 cols, isort, flake8) & `sdlc-test-driven-development` (pytest unit & edge tests).
- **Post-Task Quality Gate**: `sdlc-posttask-quality-gate` (100% pytest pass, linters, git diff), `sdlc-security-audit` (secret prevention, input sanitization), `sdlc-conventional-commit` (conventional commits via agy-cli).


See full details in [Agent.md](file:///d:/herness_agent/Agent.md).
