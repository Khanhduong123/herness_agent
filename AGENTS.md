# AGENTS.md: Rules and Architecture Guidelines for AI Agents

> [!NOTE]
> This is the unified system rule file outlining the architectural guidelines, roles, and strict compliance rules for all AI Agents operating within this repository.

> [!CAUTION]
> ### 🚨 RULE 0: ZERO-TOLERANCE CODE-WRITING LOCK FOR ORCHESTRATOR
> **When operating via `agy` or acting as the Central Orchestrator, YOU ARE STRICTLY PROHIBITED FROM DIRECTLY WRITING, MODIFYING, OR REFACTORING APPLICATION SOURCE CODE (`src/`, `tests/`, etc.).**
>
> If the user requests to "implement feature X", "fix bug Y", "write code", or "refactor":
> 1. **DO NOT touch application code directly.** Calling `replace_file_content`, `apply_patch`, or `write_to_file` on application code files is a critical system violation.
> 2. **DO NOT write code yourself.** Coding is exclusively the responsibility of a dedicated **Coder Worker Agent**.
> 3. **YOUR ORCHESTRATOR WORKFLOW IS STRICTLY**:
>    - **Decompose & Plan**: Formulate a Task DAG with mandatory `plan_id` in `.ai/plans/main/YYYY-MM-DD/main_[plan_id].md` and Sub-Specs in `.ai/plans/subtasks/YYYY-MM-DD/[plan_id]/subtask_01_[task_id].md`.
>    - **Wait for User Approval**: Present the plan to the user before any workspace setup or worker launch.
>    - **Setup Workspace**: Create an isolated git worktree via Herdr (`herdr workspace create agent/[task_id]`).
>    - **Dispatch to Worker**: Launch a specialized Coder Agent (`herdr agent start worker_[task_id] --kind agy --pane <pane>` or `harness-agent orchestrate`).
>    - **Quality Gate & Critics**: Dispatch diffs in parallel to the 3 Adversarial Critics and verify 100% pytest pass rate.

---

## 1. System Architecture: Central Orchestrator Pattern

The system uses a **Central Orchestrator Pattern** to coordinate specialized **Worker Agents**:

```mermaid
graph TD
    User["User / Task Request"] --> Orchestrator["Central Orchestrator (AgentHarness / Orchestrator)"]

    subgraph "Herdr Terminal Multiplexer / Workspaces"
        Orchestrator -->|Decomposes & Dispatches| Researcher["Researcher Agent<br/>(Analyze & Blueprint)"]
        Orchestrator -->|Assigns Feature Code| Coder["Coder Agent<br/>(Implementation)"]
        Orchestrator -->|Dispatches Test Suite| Tester["Tester Agent<br/>(QA & Pytest)"]
        Orchestrator -->|Dispatches Diff in Parallel| Critics["Parallel Adversarial Critics"]
        Critics --> SecurityReviewer["Security Reviewer Agent<br/>(Vulnerabilities & Injections)"]
        Critics --> PerformanceReviewer["Performance Reviewer Agent<br/>(Complexity & O(N^2) Loops)"]
        Critics --> RequirementReviewer["Requirement Reviewer Agent<br/>(Spec & Acceptance Criteria)"]
    end

    Researcher -->|Context & Specs| Orchestrator
    Coder -->|Code Diffs & Artifacts| Orchestrator
    Tester -->|Test Reports & Tracebacks| Orchestrator
    SecurityReviewer -->|Security Feedback| Orchestrator
    PerformanceReviewer -->|Performance Feedback| Orchestrator
    RequirementReviewer -->|Requirement Feedback| Orchestrator

    Orchestrator -->|Aggregated Review Feedback| Coder
    Orchestrator -->|Final Result & Verification| Output["Validated Deliverable"]
```

| Role | Identifier | Key Responsibilities |
| :--- | :--- | :--- |
| **Orchestrator** | `orchestrator` | • Receives the goal from the User.<br/>• Decomposes the goal into a Task DAG.<br/>• **CRITICAL RULE:** NEVER write or edit code files directly. Wait for approval, create a git worktree, and setup a Herdr workspace.<br/>• **CRITICAL RULE (Mandatory Plan ID & Local Storage):** DO NOT create UI Artifacts. MUST explicitly write all plans directly to `.ai/plans/main/YYYY-MM-DD/` and `.ai/plans/subtasks/YYYY-MM-DD/` using standard file paths. Every plan MUST declare a unique `plan_id` (e.g., `plan_[feature_name]`). Master Task DAGs MUST be stored as `.ai/plans/main/YYYY-MM-DD/main_[plan_id].md` with YAML frontmatter containing `plan_id`. Individual Sub-Specs MUST be stored in dedicated plan folders with 2-digit zero-padded numbers: `.ai/plans/subtasks/YYYY-MM-DD/[plan_id]/subtask_01_[task_id].md` referencing both `Plan ID: [plan_id]` and `Task ID: [task_id]`. This prevents file overwriting across multiple plans and guarantees clean numerical ordering.<br/>• **CRITICAL RULE (Sub-Agent Domain Expertise):** Every sub-agent MUST be a dedicated domain expert focused exclusively on that 1 assigned task and MUST strictly adhere to system rules.<br/>• **DO NOT run `agy` in the background**. Launch interactively (`herdr agent start worker_[task_id] --kind agy --pane <pane_id>`) and send prompts via `herdr agent prompt`.<br/>• **MANDATORY:** Must check if the CLI ran and wait for the completion signal before proceeding. |
| **Researcher** | `researcher` | • Explores the codebase, dependencies, and available libraries.<br/>• Designs architectural blueprints before implementation begins. |
| **Coder** | `coder`, `agent-backend`, etc. | • Implements feature code, strictly adhering to PEP 8, typing, and the provided spec.<br/>• **CRITICAL RULE ("Patch, Never Regenerate"):** MUST NEVER rewrite or overwrite entire existing files. MUST ONLY apply minimal diff hunks using patch-based tools (`apply_patch`, `replace_file_content`, `multi_replace_file_content`). Full-file overwrites are tool-locked and strictly forbidden.<br/>• **Domain Expert Rule:** The Orchestrator configures this sub-agent as a specialized domain expert (e.g., `agent-backend` for APIs) strictly dedicated to its 1 assigned subtask and compliant with all quality gates. |
| **Tester** | `tester` | • Writes unit and integration tests using `pytest` and `pytest-asyncio`.<br/>• Validates a 100% pass rate before hand-off. |
| **Security Reviewer** | `security_reviewer`, `security-reviewer` | • Evaluates code diffs and files for vulnerabilities, injection flaws (SQLi, shell injection, XSS), hardcoded secrets, and unsafe deserialization. |
| **Performance Reviewer** | `performance_reviewer`, `performance-reviewer` | • Evaluates code diffs for algorithmic efficiency, nested loops (O(N^2) complexity), memory leaks, and performance bottlenecks. |
| **Requirement Reviewer** | `requirement_reviewer`, `requirement-reviewer` | • Evaluates code against functional specifications, acceptance criteria, and sub-spec contracts. |
| **Reviewer** | `reviewer` | • Evaluates code diffs, linting, typing, conventions, and security.<br/>• Verifies that code modifications are atomic diff patches rather than full-file regenerations (retained for backward compatibility). |

### 1.1. Adversarial Critics Review Protocol
When a **Coder** completes a feature implementation or code change:
1. **Parallel Dispatch**: The Orchestrator automatically extracts the code diff / output and dispatches it concurrently to all 3 adversarial critics (`Security Reviewer`, `Performance Reviewer`, `Requirement Reviewer`) in parallel via `asyncio.gather`.
2. **Specialized Scrutiny**: Each critic focuses exclusively on its domain of expertise without overlapping biases.
3. **Feedback Aggregation**: The Orchestrator aggregates all critic evaluations into an `AggregatedCriticReview`.
4. **Coder / Patcher Remediation**: If defects or vulnerabilities are detected (e.g., SQL injection or quadratic loops), the aggregated feedback is routed directly back to the Coder / Patcher for remediation.

---

## 2. Environment & Tooling Standards

All agents must strictly adhere to the following environment rules:

### 2.1. Conda Environment
- **Mandatory:** Always use the **`pytorch`** conda environment.
- Run commands using: `conda run -n pytorch <command>`

### 2.2. Python Standards
- **Version:** `>= 3.10`
- **Typing:** 100% type hints on all public interfaces (use Pydantic v2 for schemas).
- **Style:** Black (100 line length), isort (profile black), flake8 (no unused imports or silent exception swallowing).
- **Documentation:** Do not delete existing, unrelated comments or docstrings.

### 2.3. Testing Gates
- All new features or bug fixes must include unit tests.
- Run tests via `conda run -n pytorch pytest`.
- **Gatekeeper Rule:** A task cannot be marked as complete if any tests fail.

### 2.4. Tool-Locking & Patching Policy ("Patch, Never Regenerate")
- **Patch-Only Rule:** All code modifications to existing files must be executed exclusively via diff hunks. Regenerating or rewriting whole files causes context rot, hallucination, and loss of unrelated comments/functions.
- **Tool-Locking:** Worker agents (especially Coder and Reviewer) are tool-locked against full-file overwrites (e.g., `write_to_file` on existing files). Any attempt to overwrite an entire file in one go will be rejected by the orchestrator and fail the quality gate.
- **Permitted Edit Tools:** `apply_patch`, `replace_file_content`, `multi_replace_file_content`.

---

## 3. Git Operations: Direct agy-cli Control

- **Separation of Concerns**: Python source code (`src/`) must NEVER call Git programmatically (e.g., no `subprocess` or `GitPython`).
- **Direct Execution**: All Git actions must be performed directly via the `agy` CLI in the terminal.
- **Strict Branch Protection & Automated Merge Lock**:
  - **Protected Branches:** `main`, `master`, `dev`, `develop`.
  - **NO AUTOMATED MERGING:** All AI agents (Orchestrator, Coder, Tester) and scripts are **STRICTLY FORBIDDEN** from automatically merging feature or bugfix branches into `main` or `dev`.
  - **NO DIRECT COMMITTING:** Committing directly to `main`, `master`, `dev`, or `develop` is strictly blocked (enforced via `.pre-commit-config.yaml` `no-commit-to-branch` hook).
  - **HUMAN-ONLY MERGE AUTHORITY:** Merging code into `main` or `dev` is exclusively reserved for the human user.
  - **Dedicated Branches Only:** Always work exclusively on dedicated branches (`feat/...`, `fix/...`, `agent/...`).
- **Conventional Commits**: Use `feat:`, `fix:`, `test:`, `docs:`, `refactor:`. Always inspect `git status` and `git diff` before committing.
- **Automated Remote Push & Pull Request Creation**:
  - After each feature or fix branch is committed, the agent **MUST automatically push** the branch to the remote repository (`git push -u origin <branch-name>`).
  - The agent **MUST create a Pull Request** targeting `main` (or `dev`) via the GitHub CLI (`gh pr create --base main --head <branch-name> --title "..." --body "..."`) or GitHub REST API.
  - The agent **MUST provide the resulting PR link directly to the user** for human review and merge authorization.
- **Rule Sync on Main Only**: Updates to standard rules and SDLC skills must only be pulled/synced into the `main` branch, not in-flight feature branches.

---

## 4. Herdr Workspace Setup (`herdr.dev`)

Herdr is the terminal multiplexer used for AI agents to maintain persistent sessions. Each worker agent should run in an isolated pane/tab.

- **Windows (PowerShell - Recommended):** `powershell -ExecutionPolicy Bypass -c "irm https://herdr.dev/install.ps1 | iex"`
- **Windows (CMD):** `curl.exe -fsSLo install.cmd https://herdr.dev/install.cmd && install.cmd && del install.cmd`
- **Unix/WSL:** `curl -fsSL https://herdr.dev/install.sh | sh`

---

## 5. Task Lifecycle & Context Passing

- **Lifecycle:** `[PENDING] --> [RUNNING] --> [VALIDATING] --> [COMPLETED] / [FAILED] / [BLOCKED]`
- **Context Passing:** The Orchestrator must provide the worker with the overall goal, specific instructions, and outputs from upstream tasks. If a task fails, record the error and optionally trigger a self-correction loop.

---

## 6. SDLC Skills Protocol (`.agents/skills/`)

Agents MUST ONLY read and apply specific skills that are relevant to their task.

### 6.1. Pre-Task Phase
- `sdlc-pretask-checklist`: Verify clean tree, checkout branch, breakdown requirements.
- `sdlc-architecture-planner`: Survey codebase, define Pydantic schemas, plan DAG.
- `sdlc-subtask-specifier`: Generate sub-specs assessing Criticality, Risk, and Function/TestCase Specs.

### 6.2. In-Task Phase
- `sdlc-clean-code-standards`: Follow PEP 8, Black, type safety.
- `sdlc-test-driven-development`: Write tests covering happy paths and edge cases.

### 6.3. Post-Task Quality Gate
- `sdlc-posttask-quality-gate`: Ensure 100% pytest pass rate, run linters, and inspect git diffs.
- `sdlc-security-audit`: Check for leaked secrets and injection vulnerabilities.
- `sdlc-conventional-commit`: Commit code directly via the terminal using conventional naming.

---

## 7. Orchestrator CLI Commands

```powershell
# Check agy CLI connectivity
conda run -n pytorch harness-agent check

# Initialize rules & skills for a new repository
conda run -n pytorch harness-agent init "..\new-project"

# Sync rule updates (MUST BE ON MAIN BRANCH)
conda run -n pytorch harness-agent sync "..\new-project"
```

---

## 8. Language & Communication Standards

- **Code, Docs, & Plans**: All generated plans, specs, code, and docs MUST be written in **English**.
- **Chat**: Agents should communicate with the user in the user's preferred language (e.g., Vietnamese) when responding in the chat UI.
