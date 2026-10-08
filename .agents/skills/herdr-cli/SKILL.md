---
name: herdr-cli
description: >-
  Operational cheatsheet and reference guide for Herdr terminal multiplexer CLI commands.
  Use when splitting panes, starting and prompting interactive AI agents, inspecting status,
  reading agent outputs, and handling timeouts without repeatedly calling 'herdr --help'.
---

# Herdr CLI Reference & Operational Skill

> [!IMPORTANT]
> **Git Worktree Policy:**
> NEVER use `herdr worktree`. ALWAYS use native `git worktree` commands (`git worktree add`, `git worktree remove`) for workspace isolation, and pass the worktree path directly to Herdr via `--cwd .worktrees/agent/<task_id>`.

---

## 1. System & Server Health

Check server and client connectivity before dispatching agents:
```powershell
herdr status
```
- Verify both client and server are running on the same version.
- Config location: `%APPDATA%\herdr\config.toml`

---

## 2. Pane Lifecycle & Layout Management

### 2.1. Inspect Pane Layout
```powershell
herdr pane layout --pane "$HERDR_PANE_ID"
```

### 2.2. Split Pane for Sub-agent
Always use `--no-focus` to avoid stealing user focus, and specify `--cwd`:
```powershell
# Split horizontally (to the right):
herdr pane split --current --direction right --cwd ".worktrees/agent/<task_id>" --no-focus

# Split vertically (downwards):
herdr pane split --current --direction down --cwd ".worktrees/agent/<task_id>" --no-focus
```
> The command returns JSON output containing `.result.pane.pane_id` (e.g. `pane_123`).

### 2.3. Inspect Pane Status & Content

> [!WARNING]
> **Anti-Polling Rule:** The Orchestrator is **strictly forbidden** from continuously polling or dumping terminal buffers (`herdr pane read` / `herdr agent read`) during worker execution. This wastes context tokens and degrades agent reasoning. Reading the buffer is permitted **only once** upon a timeout or fatal error to inspect tracebacks.

```powershell
# Query pane state:
herdr pane get <pane_id>

# Read recent terminal output (strictly capped at 20 lines for diagnostics):
herdr pane read <pane_id> --source recent-unwrapped --lines 20

# Available read sources:
# - visible: Currently rendered viewport
# - recent: Recent rendered output with soft wraps
# - recent-unwrapped: Recent output with soft wraps joined (recommended for logs)
# - detection: Plain-text bottom-buffer snapshot
```

### 2.4. Close Pane
```powershell
herdr pane close <pane_id>
```

---

## 3. Agent Lifecycle Management (`herdr agent`)

### 3.1. Start an Interactive Agent
Launch an agent in a designated pane. Use `--system-prompt-file` to preload the worker role skill/prompt file directly, `--thinking-level low` for leaf workers, and pass dynamic domain skills via one or multiple `--skill-file` flags after `--`:
```powershell
# Starting a Coder Worker with injected domain skills:
herdr agent start worker_<task_id> `
  --kind agy `
  --pane <pane_id> `
  --cwd .worktrees/agent/<task_id> -- `
  --system-prompt-file .agents/skills/coder_worker.md `
  --skill-file .agents/skills/sdlc-api-interface-design/SKILL.md `
  --skill-file .agents/skills/sdlc-clean-code-standards/SKILL.md `
  --thinking-level low `
  --dangerously-skip-permissions

# Starting a Ceremony / Research Sub-Agent (Scrum Master, Standup, AI Paper Researcher):
herdr agent start scrum_planner_01 `
  --kind agy `
  --pane <pane_id> `
  --cwd . -- `
  --system-prompt-file .agents/skills/researcher_worker.md `
  --skill-file .agents/skills/sdlc-scrum-master/SKILL.md `
  --skill-file .agents/skills/sdlc-planning-task-breakdown/SKILL.md `
  --thinking-level low `
  --dangerously-skip-permissions
```
- `--system-prompt-file <path>`: Preloads system prompt file into the worker at launch.
- `--skill-file <path>`: Injects domain skills into the worker context at launch. Can be passed multiple times (max 2–3 skills to avoid context dilution). Paths must be valid relative/absolute paths ending in `SKILL.md`.
- **Two-Tier Skill Routing**:
  - **Tier 1 (Intent & Ceremony Matching)**: Ceremony and research tasks (`scrum`, `standup`, `paper research`, `poc`) route to `researcher_worker.md` with ceremony skills (e.g. `sdlc-scrum-master`, `sdlc-daily-standup-planner`, `sdlc-ai-paper-researcher`).
  - **Tier 2 (Target Path Matching)**: Code implementation tasks route to `coder_worker.md` or `tester_worker.md` with implementation skills based on directory paths (`src/api/`, `src/ui/`, `tests/`).
- Available kinds: `agy`, `codex`, `claude`, `gemini` (run `herdr agent` to check installed kinds).
- Returns when the agent is detected and ready for input (settled `idle`).

### 3.2. Prompt the Agent
Submit a task using the mandatory multi-line PowerShell here-string dispatch contract:
```powershell
herdr agent prompt worker_<task_id> @"
[ROLE: Leaf Coder Worker]
Spec: .ai/plans/subtasks/YYYY-MM-DD/<plan_id>/subtask_01_<task_id>.md
Prohibitions: No ManageTask, no background loops, no full-file overwrite.
Target: 100% pytest pass -> write .ai/status/<task_id>.complete -> output [WORKER_COMPLETED].
"@
```
*(Note: In PowerShell, the closing `"@` must be at column 0 without leading whitespace).*

#### Synchronous / Waiting Prompt:
```powershell
# Wait for the agent to finish its turn (timeout in milliseconds):
herdr agent prompt worker_<task_id> "..." --wait --timeout 120000
```
- `--wait`: Waits until the agent settles into `idle`, `done`, or `blocked`.
- `--timeout <ms>`: Hard timeout ceiling (e.g., 60000 for 60s, 120000 for 2m).

### 3.3. Check Agent State & Read Responses
```powershell
# Get live state (idle, working, blocked, done):
herdr agent get worker_<task_id>

# Read agent output:
herdr agent read worker_<task_id> --source recent-unwrapped --lines 100
```

### 3.4. Wait on an Agent

> [!IMPORTANT]
> **Deterministic Blocking Wait (Zero LLM Tokens):**
> Always use long timeouts (300s–600s) for agent execution turns. Short timeouts (30s–60s) trigger artificial timeout failures and panic polling loops. `harness-agent wait` blocks in local Python while checking `.ai/status/<task_id>.complete`, consuming zero LLM tokens.

```powershell
# Primary: Blocking wait via harness-agent CLI (detects completion flag automatically):
conda run -n pytorch harness-agent wait <task_id> --timeout 600

# Alternative: Socket-level wait via Herdr (300s):
herdr agent wait worker_<task_id> --timeout 300000

# Wait for a specific state if debugging (e.g. blocked, waiting for input):
herdr agent wait worker_<task_id> --until blocked --timeout 300000
```

### 3.5. Send Interactive Keystrokes
To interrupt or send keys to an interactive agent:
```powershell
herdr agent send-keys worker_<task_id> ctrl+c
herdr agent send-keys worker_<task_id> esc
herdr agent send-keys worker_<task_id> enter
```

### 3.6. Stop or Terminate an Agent
To terminate a worker process and close its associated pane:
```powershell
# Terminate worker process / close pane:
herdr pane close <pane_id>
```

### 3.7. Subtask Rollback & Abort Commands
If a subtask encounters an unrecoverable failure or exceeds 3 Critic rejection cycles:
```powershell
# 1. Capture diagnostic git diff to failure log:
git diff feat/<feature_name>...agent/<task_id> > .ai/failures/<task_id>_diff.log

# 2. Terminate Herdr worker pane:
herdr pane close <pane_id>

# 3. Clean up worktree and delete abandoned subtask branch:
git worktree remove --force .worktrees/agent/<task_id>
git branch -D agent/<task_id>
```

---

## 4. Standard Orchestrator Dispatch Pattern

```powershell
# 1. Create isolated Git worktree branching from feature branch:
git worktree add -b agent/<task_id> .worktrees/agent/<task_id> feat/<feature_name>

# 2. Worktree Environment Setup (copy .env files if present):
Copy-Item -Path ".env*" -Destination ".worktrees/agent/<task_id>/" -ErrorAction SilentlyContinue

# 3. Launch interactive Coder worker in the pane with injected domain skills:
herdr agent start worker_<task_id> `
  --kind agy `
  --pane <pane_id> `
  --cwd .worktrees/agent/<task_id> -- `
  --system-prompt-file .agents/skills/coder_worker.md `
  --skill-file .agents/skills/sdlc-api-interface-design/SKILL.md `
  --skill-file .agents/skills/sdlc-clean-code-standards/SKILL.md `
  --thinking-level low `
  --dangerously-skip-permissions

# (Optional: Dispatching a Ceremony / Research worker e.g. Scrum Master, AI Paper Researcher):
# herdr agent start scrum_planner_01 --kind agy --pane <pane_id> --cwd . -- `
#   --system-prompt-file .agents/skills/researcher_worker.md `
#   --skill-file .agents/skills/sdlc-scrum-master/SKILL.md `
#   --skill-file .agents/skills/sdlc-planning-task-breakdown/SKILL.md `
#   --thinking-level low `
#   --dangerously-skip-permissions

# 4. Dispatch task with mandatory multi-line dispatch contract:
herdr agent prompt worker_<task_id> @"
[ROLE: Leaf Coder Worker]
Spec: .ai/plans/subtasks/YYYY-MM-DD/<plan_id>/subtask_01_<task_id>.md
Prohibitions: No ManageTask, no background loops, no full-file overwrite.
Target: 100% pytest pass -> write .ai/status/<task_id>.complete -> output [WORKER_COMPLETED].
"@
# (Note: In PowerShell, the closing "@ must be at column 0 without leading whitespace)

# 5. Monitor progress (deterministic blocking wait, zero token consumption):
# Primary: Blocking wait via harness-agent CLI (detects .ai/status/<task_id>.complete automatically):
conda run -n pytorch harness-agent wait <task_id> --timeout 600
# Alternative: Herdr agent wait (300s):
herdr agent wait worker_<task_id> --timeout 300000

# Confirm completion flag file exists:
Test-Path ".ai/status/<task_id>.complete"

# Single diagnostic read ONLY on timeout / failure (strictly capped at 20 lines):
herdr agent read worker_<task_id> --source recent-unwrapped --lines 20

# 6. Success Flow: Merge back, cleanup pane first, full regression, and open PR:
git merge --no-ff agent/<task_id>
herdr pane close <pane_id>
git worktree remove --force .worktrees/agent/<task_id>
git branch -d agent/<task_id>
conda run -n pytorch pytest tests/
git push -u origin feat/<feature_name>
conda run -n pytorch harness-agent pr create --base main

# 7. Abort Flow (if timed out or failed 3 critic cycles):
git diff feat/<feature_name>...agent/<task_id> > .ai/failures/<task_id>_diff.log
herdr pane close <pane_id>
git worktree remove --force .worktrees/agent/<task_id>
git branch -D agent/<task_id>
```
