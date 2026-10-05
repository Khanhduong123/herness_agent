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
```powershell
# Query pane state:
herdr pane get <pane_id>

# Read recent terminal output (unwrapped lines):
herdr pane read <pane_id> --source recent-unwrapped --lines 120

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
Launch an agent in a designated pane. Arguments after `--` are passed directly to the agent binary:
```powershell
herdr agent start worker_<task_id> --kind agy --pane <pane_id> --cwd .worktrees/agent/<task_id> -- --dangerously-skip-permissions
```
- Available kinds: `agy`, `codex`, `claude`, `gemini` (run `herdr agent` to check installed kinds).
- Returns when the agent is detected and ready for input (settled `idle`).

### 3.2. Prompt the Agent
Submit a task with Role Anchoring:
```powershell
herdr agent prompt worker_<task_id> "[SYSTEM CONTEXT: You are a leaf implementation worker. You CANNOT plan or dispatch other agents. Only write code and run tests in your worktree.] Read .ai/plans/subtasks/YYYY-MM-DD/<plan_id>/subtask_01_<task_id>.md and implement with 100% pytest pass rate."
```

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
```powershell
# Wait until idle or done (default settled state):
herdr agent wait worker_<task_id> --timeout 120000

# Wait for a specific state (e.g. blocked, waiting for input):
herdr agent wait worker_<task_id> --until blocked --timeout 60000
```

### 3.5. Send Interactive Keystrokes
To interrupt or send keys to an interactive agent:
```powershell
herdr agent send-keys worker_<task_id> ctrl+c
herdr agent send-keys worker_<task_id> esc
herdr agent send-keys worker_<task_id> enter
```

---

## 4. Standard Orchestrator Dispatch Pattern

```powershell
# 1. Create isolated Git worktree using NATIVE git:
git worktree add -b agent/<task_id> .worktrees/agent/<task_id>

# 2. Split a Herdr pane directed into the worktree:
# herdr pane split --current --direction right --cwd ".worktrees/agent/<task_id>" --no-focus

# 3. Launch interactive Coder worker in the pane:
herdr agent start worker_<task_id> --kind agy --pane <pane_id> --cwd .worktrees/agent/<task_id> -- --dangerously-skip-permissions

# 4. Dispatch task with Role Anchor:
herdr agent prompt worker_<task_id> "[SYSTEM CONTEXT: You are a leaf implementation worker. You CANNOT plan or dispatch other agents. Only write code and run tests in your worktree.] Read .ai/plans/subtasks/YYYY-MM-DD/<plan_id>/subtask_01_<task_id>.md and implement with 100% pytest pass rate."

# 5. Monitor progress (active query, no stream-of-consciousness waiting):
herdr agent get worker_<task_id>
herdr agent read worker_<task_id> --source recent-unwrapped --lines 60

# 6. Quality gates passed? Push, open PR, and clean up native git worktree:
git push -u origin agent/<task_id>
conda run -n pytorch harness-agent pr create --base main
git worktree remove .worktrees/agent/<task_id>
```
