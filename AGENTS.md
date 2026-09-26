# AGENTS.md: Rules and Architecture Guidelines for AI Agents

> [!NOTE]
> This file mirrors [Agent.md](file:///d:/herness_agent/Agent.md) to ensure full compatibility with standard workspace rule scanners, Antigravity IDE, and Herdr workspaces.

## 1. System Architecture: Central Orchestrator & Workers

This repository uses a **Central Orchestrator Pattern**:
- **Orchestrator (`orchestrator`)**: Plans, coordinates DAG tasks, routes context, monitors status, and verifies completion.
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

## 3. Git Rules

- Never commit directly to `main`.
- Always work on a dedicated branch (`feat/...`, `fix/...`).
- Current branch: `feat/orchestrator-architecture`.
- Use conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`).

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

See full details in [Agent.md](file:///d:/herness_agent/Agent.md).
