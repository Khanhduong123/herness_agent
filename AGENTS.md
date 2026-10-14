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
> 3. **FORBIDDEN TOOLS (`invoke_subagent`, `define_subagent`):** Spawning hidden background agents is strictly forbidden. All worker agents must be dispatched interactively via Herdr terminal panes.
> 4. **YOUR ORCHESTRATOR WORKFLOW IS STRICTLY**:
>    - **Decompose & Plan**: Formulate Task DAG in `.ai/plans/main/YYYY-MM-DD/main_[plan_id].md` and Sub-Specs in `.ai/plans/subtasks/YYYY-MM-DD/[plan_id]/subtask_01_[task_id].md`.
>    - **Wait for User Approval**: Present plan before workspace setup or dispatch.
>    - **Setup Workspace**: Create isolated git worktree (`git worktree add -b agent/<task_id> .worktrees/agent/<task_id>`).
>    - **Dispatch to Worker**: Launch Coder Agent (`herdr agent start worker_[task_id] --kind agy --pane <pane> --cwd .worktrees/agent/<task_id> -- --effort low --dangerously-skip-permissions`) and prompt via dispatch contract template (`herdr agent prompt worker_[task_id] @"..."@`).
>    - **Quality Gate & Critics**: Dispatch diffs in parallel to 3 Adversarial Critics; verify 100% pytest pass rate.

---

## STANDARD AGENT RBAC MATRIX (ROLE-BASED ACCESS CONTROL)

| Responsibility / Capability | Coder Worker | Tester / Critics | Central Orchestrator | User (Human) |
| :--- | :---: | :---: | :---: | :---: |
| **Formulate Task DAG & Spec (`.ai/plans/`)** | ❌ | ❌ | ✅ | 🔄 Approve / Amend |
| **Create / Remove Git Worktree** | ❌ | ❌ | ✅ | ❌ |
| **Dispatch Panes via Herdr** | ❌ | ❌ | ✅ | ❌ |
| **Modify Application Source Code** | ✅ *(In Worktree only)* | ❌ | 🚫 *(FORBIDDEN - Rule 0)* | ❌ |
| **Run `pytest` & Self-Tests** | ✅ | ✅ | 🔍 *(Read test reports only)* | ❌ |
| **Quality Evaluation (Adversarial Review)** | ❌ | ✅ *(Read-only diffs)* | 🔍 *(Aggregate feedback)* | ❌ |
| **Open Pull Request (`harness-agent pr create`)** | ❌ | ❌ | ✅ | ❌ |
| **Merge into Protected Branch (`main`/`dev`)** | ❌ | ❌ | 🚫 **(STRICTLY FORBIDDEN)** | 👑 **(Review & Merge)** |

---

## 4-TIER ARCHITECTURAL CONSTRAINTS & WORKFLOW PROTOCOL

### Tier 1: Infrastructure & Tool-Level Guardrails
- **Zero Root-Repo Mutations:** Orchestrator never modifies files directly in root. Internal subagents (`invoke_subagent`, `define_subagent`) are strictly locked out.
- **Mandatory Git Worktree Isolation:** Code edits MUST run in an isolated Git worktree: `git worktree add -b agent/<task_id> .worktrees/agent/<task_id> feat/<feature_name>`. Copy `.env*` files to worktree if present.
- **Multiplexer Workspace Protocol:** Launch workers interactively in explicit Herdr panes with low effort and bypass permissions:
  `herdr agent start worker_<task_id> --kind agy --pane <pane_id> --cwd .worktrees/agent/<task_id> -- --effort low --dangerously-skip-permissions`
- **Socket/Prompt Dispatch Contract:** Dispatch prompts strictly via Herdr socket:
  ```powershell
  herdr agent prompt worker_<task_id> @"
  [ROLE: Leaf Coder Worker]
  Spec: .ai/plans/subtasks/<date>/<plan_id>/subtask_<id>.md
  Required Skills: sdlc-clean-code-standards
  Prohibitions: No ManageTask, no background loops, no full-file overwrite.
  Target: 100% pytest pass -> write .ai/status/<task_id>.complete -> output [WORKER_COMPLETED].
  Instructions: Read assigned spec and activate required skills before implementing code changes.
  "@
  ```
- **Background Task & Polling Lockout:** No background loops (`ManageTask`) or `schedule` polling for workers or orchestrator tracking workers.

### Tier 2: Role Isolation & Anti-Role-Drift
- **Dedicated Role Prompts & Skill Delivery:** Never share `AGENTS.md` with workers. Roles are anchored via prompt headers; skills delivered via the 3-Tier Delivery Protocol.
- **Role Anchors:** Researcher/Specifier (`[ROLE: Architecture Planner / Contract Specifier]`), Coder (`[ROLE: Leaf Coder Worker]`), Critic (`[ROLE: Adversarial Critic]`), Tester (`[ROLE: QA & Tester Worker]`).
- **Strict Leaf Worker Boundaries & Read-Only Critics:** Leaf workers only code/test; Critics only evaluate diffs (read-only). Coder worker locked to synchronous blocking commands with `--effort low`.

### Tier 3: Anti-Spinlock, Timeout & Loop Truncation
- **Ban on Terminal Polling:** NEVER continuously call `herdr pane read` or `herdr agent read`. Polling terminal buffers floods the context window.
- **Deterministic Blocking Wait:** `conda run -n pytorch harness-agent wait <task_id> --timeout 600` (or `herdr agent wait worker_<task_id> --timeout 300000`).
- **Single-Read-On-Timeout Policy:** Only on wait timeout/error, execute ONE diagnostic read: `herdr agent read worker_<task_id> --source recent-unwrapped --lines 20`.
- **Authoritative Completion Signal:** `.ai/status/<task_id>.complete` is the sole authoritative trigger.
- **Loop Truncation & Rollback:** Max 3 rejection cycles between Coder and Critics/Pytest. On abort: log to `.ai/failures/`, close pane (`herdr pane close <pane_id>`), remove worktree (`git worktree remove --force .worktrees/agent/<task_id>`), delete branch (`git branch -D agent/<task_id>`), escalate to User.

### Tier 4: Human-in-the-Loop (HITL) & Automated PR Gate
- **Strict Merge Lock & Human Authority:** Merging into `main` or `dev` is exclusively reserved for the human user.
- **Automated PR Gate Protocol:** On approval (100% pytest pass + 3 Critics PASS):
  1. Merge subtask: `git merge --no-ff agent/<task_id>`
  2. Cleanup: close worker pane, `git worktree remove --force .worktrees/agent/<task_id>`, `git branch -d agent/<task_id>`.
  3. Regression: `conda run -n pytorch pytest tests/`
  4. Critics Gate: `conda run -n pytorch harness-agent review --base main`
  5. Push & PR: `git push -u origin feat/<feature_name>` -> `conda run -n pytorch harness-agent pr create --base main` -> provide PR link to User.

---

## 1. System Architecture: Central Orchestrator Pattern

The system uses a **Central Orchestrator Pattern** to coordinate specialized **Worker Agents** via Herdr terminal multiplexer:
- **Planning & Blueprint**: Orchestrator assigns DAG planning and contract specifications to Researcher/Specifier.
- **Implementation**: Feature code is assigned to Coder in isolated Git worktrees.
- **Testing & Adversarial Review**: Test suites and git diffs are evaluated concurrently by Tester and Adversarial Critics (Security, Performance, Requirements).

| Role | Identifier | Key Responsibilities |
| :--- | :--- | :--- |
| **Orchestrator** | `orchestrator` | Receives goal, plans Task DAG in `.ai/plans/main/YYYY-MM-DD/main_[plan_id].md` and Sub-Specs in `.ai/plans/subtasks/YYYY-MM-DD/[plan_id]/subtask_01_[task_id].md` with edge cases. Creates isolated worktrees (`git worktree add -b agent/<task_id> .worktrees/agent/<task_id>`). Dispatches workers interactively via Herdr (`herdr agent start worker_[task_id] --kind agy --pane <pane> --cwd .worktrees/agent/<task_id> -- --effort low --dangerously-skip-permissions`). Never writes code directly (Rule 0). |
| **Researcher** | `researcher` | Explores codebase, dependencies, and architectures; writes blueprints and specs. |
| **Coder** | `coder`, `agent-backend` | Implements feature code in isolated worktree using patch tools only ("Patch, Never Regenerate"). Runs unit tests. |
| **Tester** | `tester` | Writes unit/integration tests in `tests/unit/` and `tests/integration/`. Validates 100% pass rate. |
| **Security Reviewer** | `security_reviewer` | Read-only critic evaluating git diffs for vulnerabilities, injections, and leaked secrets. |
| **Performance Reviewer** | `performance_reviewer` | Read-only critic evaluating git diffs for complexity, nested loops, and memory leaks. |
| **Requirement Reviewer** | `requirement_reviewer` | Read-only critic verifying git diffs against sub-spec contracts and acceptance criteria. |

### 1.1. Adversarial Critics Review Protocol & Workflow Optimization
When a **Coder** completes implementation:
1. **Parallel Dispatch**: Orchestrator dispatches diff concurrently to the 3 adversarial critics (`Security Reviewer`, `Performance Reviewer`, `Requirement Reviewer`).
2. **Aggregated Evaluation**: Orchestrator aggregates critic feedback into `AggregatedCriticReview`.
3. **Remediation Loop**: Routed to Coder if defects are detected (Max 3 iterations; escalates to User if rejected 3 times).
4. **Diff Guardrails**: Diffs > 500 lines or containing binaries must be split/filtered before LLM evaluation.
5. **PR Gate Enforcement**: `conda run -n pytorch harness-agent pr create` enforces the Critics Gate before PR creation.

---

## 2. Environment & Tooling Standards

- **Environment**: Python `>= 3.10` in Conda `pytorch` (`conda run -n pytorch <command>`).
- **Style**: Black (100 char limit), isort (black), flake8. Maintain comments and docstrings.
- **Test Structure**: Tests must reside in `tests/unit/` (isolated logic/mocks) or `tests/integration/` (end-to-end, CLI, processes). Never place tests in root of `tests/`.
- **Quality Gates**: 100% pytest pass rate. Full regression suite (`conda run -n pytorch pytest tests/`) must pass before PR.
- **Tool-Locking ("Patch, Never Regenerate")**: Existing files must ONLY be modified using patch tools (`apply_patch`, `replace_file_content`, `multi_replace_file_content`). Full-file overwrites on existing files are strictly locked. `write_to_file` is permitted only for brand-new files.

---

## 3. Git Operations: Terminal Execution & Tool Boundaries

- **Tool Boundaries**: Python source (`src/`) must NEVER call Git directly. All git operations run in the terminal shell. Worktree isolation uses `git worktree add -b agent/<task_id> .worktrees/agent/<task_id>`.
- **Merge Lock**: Merging to protected branches (`main`, `master`, `dev`) is exclusively reserved for the human user. Automated merges are strictly forbidden. Always use feature branches (`feat/...`).
- **Feature Branch & Worktree Hierarchy**:
  1. Branch feature: `git checkout -b feat/<name> main`
  2. Provision subtask: `git worktree add -b agent/<task_id> .worktrees/agent/<task_id> feat/<name>`
  3. Worker develops, tests, and commits atomically on `agent/<task_id>`.
  4. Merge back: `git merge --no-ff agent/<task_id>`
  5. Cleanup: close pane, `git worktree remove --force .worktrees/agent/<task_id>`, `git branch -d agent/<task_id>`.
  6. Full regression & critics gate: `conda run -n pytorch pytest tests/` -> `conda run -n pytorch harness-agent review --base main`.
  7. Push & PR: `git push -u origin feat/<name>` -> `conda run -n pytorch harness-agent pr create --base main` -> provide PR link to user.
- **Commits**: Conventional prefixes (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`). Recover from pre-commit hook reformats by re-staging (`git add .`) and committing again until exit code 0. Standard rules/skills sync only to `main`.

---

## 4. Herdr Workspace Setup (`herdr.dev`)

Herdr multiplexer runs isolated worker panes (`irm https://herdr.dev/install.ps1 | iex` on Windows, `curl -fsSL https://herdr.dev/install.sh | sh` on Unix/WSL).

---

## 5. Task Lifecycle & Context Passing

Lifecycle: `[PENDING] --> [RUNNING] --> [VALIDATING] --> [COMPLETED] / [FAILED] / [BLOCKED]`. Orchestrator passes goal, specs, and upstream outputs; triggers self-correction loops on failure.

---

## 6. SDLC Skills Reference (`.agents/skills/`)

- **Pre-Task**: `sdlc-pretask-checklist`, `sdlc-architecture-planner`, `sdlc-subtask-specifier`
- **In-Task**: `sdlc-clean-code-standards`, `sdlc-test-driven-development`
- **Post-Task**: `sdlc-posttask-quality-gate`, `sdlc-security-audit`, `sdlc-conventional-commit`

### 6.1. Dynamic Skill Injection Protocol (3-Tier Delivery)
1. **Tier 1 (Native Discovery)**: Skills exist in `.agents/skills/<name>/SKILL.md` in repository worktrees.
2. **Tier 2 (Sub-Spec Declaration)**: Sub-Specs explicitly list required domain skills and paths.
3. **Tier 3 (Herdr Prompt Injection)**: Orchestrator passes required skill names in the worker dispatch prompt.

---

## 7. Orchestrator Operational Commands Quick Reference

```powershell
# 1. Connectivity & worktree setup
conda run -n pytorch harness-agent check
git worktree add -b agent/<task_id> .worktrees/agent/<task_id> feat/<feature_name>
Copy-Item -Path ".env*" -Destination ".worktrees/agent/<task_id>/" -ErrorAction SilentlyContinue

# 2. Launch Interactive Worker (valid agy flags)
herdr agent start worker_<task_id> --kind agy --pane p_worker --cwd .worktrees/agent/<task_id> -- --effort low --dangerously-skip-permissions

# 3. Prompt Worker via Dispatch Contract
herdr agent prompt worker_<task_id> @"
[ROLE: Leaf Coder Worker]
Spec: .ai/plans/subtasks/<date>/<plan_id>/subtask_<id>.md
Required Skills: sdlc-clean-code-standards
Prohibitions: No ManageTask, no background loops, no full-file overwrite.
Target: 100% pytest pass -> write .ai/status/<task_id>.complete -> output [WORKER_COMPLETED].
Instructions: Read assigned spec and activate required skills before implementing code changes.
"@

# 4. Blocking wait (no polling)
conda run -n pytorch harness-agent wait <task_id> --timeout 600

# 5. Critics Gate, cleanup & PR
git merge --no-ff agent/<task_id>
herdr pane close <pane_id>
git worktree remove --force .worktrees/agent/<task_id>
git branch -d agent/<task_id>
conda run -n pytorch pytest tests/
conda run -n pytorch harness-agent review --base main
git push -u origin feat/<feature_name>
conda run -n pytorch harness-agent pr create --base main
```

---

## 8. Language & Communication Standards

- **Code, Docs, & Plans**: All plans, specs, code, and docs MUST be in **English**.
- **Chat**: Communicate in the user's preferred language.
- **ASCII Status Formatting**: Use plain ASCII indicators (`[OK]`, `[ERROR]`, `[PASSED]`, `[FAILED]`, `[TASK_DONE]`) in code, logs, and CLI output; emojis are permitted in Markdown docs.
- **Context Invariance**: Orchestrator must provide identical granular constraints and role anchors regardless of input language without summarizing prompts.
