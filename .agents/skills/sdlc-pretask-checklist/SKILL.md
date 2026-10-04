---
name: sdlc-pretask-checklist
description: >-
  Standard operating procedure before starting any task in the SDLC.
  Use before writing code to verify git branch, examine codebase, clarify requirements,
  and construct an architectural execution plan.
---

# SDLC Pre-Task Checklist: Preparation & Alignment

This skill defines the mandatory protocol every AI agent must execute **BEFORE** modifying or writing code.

---

## 0. Read Architecture & Role Verification
- [ ] **Read `AGENTS.md`**: Before doing anything else, read `AGENTS.md` in the repository root to align with system architecture, Git rules, environment setup, and SDLC standards.
- [ ] **Orchestrator Role Lock (CRITICAL)**:
  - **Are you the Central Orchestrator?**
    - If **YES**: **STOP IMMEDIATELY BEFORE MODIFYING ANY APPLICATION CODE.** The Orchestrator is strictly forbidden from writing or editing source code (`src/`, `tests/`). Your deliverable is exclusively:
      1. Create Master Plan in `.ai/plan/main_[plan_id].md` and Sub-Specs in `.ai/plan/subtask_[task_id].md`.
      2. Request User Approval.
      3. Create isolated workspace (`agent/[task_id]`).
      4. Dispatch to a dedicated Coder Worker Agent (`herdr agent start worker_[task_id] --kind agy`).
  - **Are you a dispatched Coder/Worker Agent?**
    - If **YES**: Proceed with the technical implementation checklist below.

---

## 1. Git & Environment Verification
- [ ] **Working Tree Check**: Run `git status` to verify there are no uncommitted or conflicting changes.
- [ ] **Branch Protection**: Verify current branch is NOT `main`.
  - If on `main`, immediately create and checkout a dedicated feature branch:
    ```bash
    git checkout -b feat/<task-name>
    # or for bugfixes:
    git checkout -b fix/<bug-name>
    ```
- [ ] **Conda Environment**: Confirm active environment is `pytorch`:
  ```powershell
  conda run -n pytorch python --version
  ```

---

## 2. Requirement Clarification & Exploration
- [ ] **Goal Extraction**: Decompose the user request into:
  - Functional requirements (what the system should do).
  - Technical constraints (Pydantic v2, Black 100 cols, Python 3.10+).
  - Out of scope items (things NOT to touch).
- [ ] **Codebase Reconnaissance**:
  - Identify relevant modules, classes, and tests using grep/search.
  - Review existing patterns to maintain architectural consistency.
  - Avoid creating duplicate utilities or parallel abstractions.

---

## 3. Technical Execution Plan (DAG)
- [ ] **Task Decomposition**: Break the implementation into small, atomic, testable steps:
  1. Define / update data schemas and types.
  2. Implement core business logic.
  3. Update or write unit tests.
  4. Run validation checks.
- [ ] **Risk Assessment**: Identify potential breaking changes or edge cases.
