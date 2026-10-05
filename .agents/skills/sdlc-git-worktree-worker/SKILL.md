---
name: sdlc-git-worktree-worker
description: >-
  Standard operating procedure for Worker Agents to create isolated workspaces using Herdr (git worktree)
  named 'agent/[task]', preventing Git conflicts and signalling the Orchestrator upon completion.
---

# SDLC Git Worktree Worker Protocol (Herdr Workspace)

This protocol enforces that every Worker Agent (e.g., Coder, Tester) must perform its assigned subtask in a clean, isolated workspace. This workspace is created as a `git worktree` using `herdr` to prevent code conflicts and ensure atomic commits.

> [!CAUTION]
> ### 🚨 STRICT PROHIBITION: NO HIDDEN BACKGROUND AGENTS (`invoke_subagent` / `define_subagent`)
> Calling `invoke_subagent` or `define_subagent` is strictly forbidden across all agents (spawns hidden background agents / 'agents ngầm'). All worker agents must be dispatched interactively via dedicated Herdr terminal panes.

## 1. Entering the Isolated Workspace & Interactive Dispatch

When a Worker Agent receives a subtask from the Orchestrator, it must **not** modify the main working directory directly. The Orchestrator manages the dispatch lifecycle through Herdr:

### Orchestrator Interactive Dispatch Lifecycle
1. **Create Isolated Worktree (Native Git)**:
   ```powershell
   git worktree add -b agent/<task_id> .worktrees/agent/<task_id>
   ```
2. **Start Interactive Worker in Dedicated Pane**:
   ```powershell
   herdr agent start worker_<task_id> --kind agy --pane <pane> --cwd .worktrees/agent/<task_id> -- --dangerously-skip-permissions
   ```
3. **Prompt Worker with Sub-Spec Contract**:
   ```powershell
   herdr agent prompt worker_<task_id> "Read .ai/plans/subtasks/YYYY-MM-DD/<plan_id>/subtask_01_<task_id>.md and implement"
   ```

### Worker Workspace Rules
1. Identify the task ID (e.g., `subtask_01_feature`).
2. The mandatory naming convention for the branch and workspace is: `agent/<task_id>`.
3. Because the Orchestrator runs the agent *inside* the dedicated worktree pane, your current working directory (`cwd`) is already the worktree (`.worktrees/agent/<task_id>`). Verify this by checking `git status` or `pwd`, and avoid `cd` commands across worktrees.

## 2. Implementing the Task

Inside the isolated workspace, the Worker Agent must:
- Read the assigned `sub-spec` (e.g., `.ai/plans/subtasks/YYYY-MM-DD/<plan_id>/subtask_01_<task_id>.md`).
- Implement the requested code changes following the "Patch, Never Regenerate" policy on existing files.
- Ensure the code adheres to all SDLC quality gates (Black, isort, flake8, pytest 100%).

## 3. Committing the Changes

Once implementation and testing are complete, the Worker Agent must commit the changes in the worktree using Conventional Commits:
```powershell
git add .
git commit -m "feat(subtask_01): implement feature according to sub-spec"
```

## 4. Signalling the Orchestrator (CRITICAL STEP)

After the commit is successful, the Worker Agent **MUST** explicitly notify the Central Orchestrator that the subtask is complete:
1. **Explicit Signal**: The Worker Agent MUST output `[WORKER_COMPLETED]` or write to `.ai/status/<task_id>.complete` so the Orchestrator knows the task is finished.
2. The notification confirms that all tests pass 100% and quality gates are satisfied.
3. The Worker Agent must return execution control, updating the task status to `COMPLETED`.

## 5. Cleanup (By Orchestrator)

The Central Orchestrator is responsible for reviewing the work, pushing the branch, creating the PR, and subsequently removing the native git worktree:
```powershell
git worktree remove .worktrees/agent/<task_id>
```
