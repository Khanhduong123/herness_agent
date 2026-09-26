---
name: sdlc-git-worktree-worker
description: >-
  Standard operating procedure for Worker Agents to create isolated workspaces using Herdr (git worktree)
  named 'agent/[task]', preventing Git conflicts and signalling the Orchestrator upon completion.
---

# SDLC Git Worktree Worker Protocol (Herdr Workspace)

This protocol enforces that every Worker Agent (e.g., Coder, Tester) must perform its assigned subtask in a clean, isolated workspace. This workspace is created as a `git worktree` using `herdr` to prevent code conflicts and ensure atomic commits.

## 1. Entering the Isolated Workspace

When a Worker Agent receives a subtask from the Orchestrator, it must **not** modify the main working directory directly. The Orchestrator should have already created a git worktree (`git worktree add agent/[task_id] -b agent/[task_id]`), created a visible workspace (`herdr workspace create --cwd ...`), and launched the agent interactively (`herdr agent start ...` and `herdr agent prompt ...`) inside that workspace.

1. Identify the task ID (e.g., `subtask_01_feature`).
2. The mandatory naming convention for the branch and workspace is: `agent/[task_id]`.
3. Because the Orchestrator runs the agent *inside* the Herdr workspace pane, your current working directory (`cwd`) should already be the worktree. Verify this by running `pwd` or checking git status, and avoid `cd ../agent/...` unless absolutely necessary.

## 2. Implementing the Task

Inside the isolated workspace, the Worker Agent must:
- Read the assigned `sub-spec`.
- Implement the requested code changes.
- Ensure the code adheres to all SDLC quality gates (Black, isort, flake8, pytest 100%).

## 3. Committing the Changes

Once implementation and testing are complete, the Worker Agent must commit the changes in the worktree using Conventional Commits:
```powershell
git add .
git commit -m "feat(subtask_01): implement feature according to sub-spec"
```

## 4. Signalling the Orchestrator

After the commit is successful, the Worker Agent must notify the Central Orchestrator that the subtask is complete.
1. The notification must include the exact workspace name/path (`agent/[task_id]`), so the Orchestrator can merge or review it.
2. The Worker Agent must return the execution control, updating the task status to `COMPLETED`.

## 5. Cleanup (By Orchestrator)

The Central Orchestrator is responsible for reviewing the work, merging the `agent/[task_id]` branch into the main feature branch, and subsequently removing the Herdr workspace (and its underlying Git worktree):
```powershell
herdr workspace remove agent/subtask_01_feature
```
