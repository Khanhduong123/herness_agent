"""Layer 2 Integration tests for parallel worktree execution across concurrent tasks.

Validates multi-task parallel plans in real temporary git repositories (tmp_path)
verifying isolated worktree directory structures, concurrent file mutations,
and cleanup without mocking SQLite, filesystems, or embedded databases.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Optional

import pytest

from harness_agent.core.models import (
    AgentRole,
    OrchestrationPlan,
    ParallelExecutionConfig,
    RunResult,
    SubTask,
    TaskStatus,
)
from harness_agent.core.orchestrator import AgentOrchestrator


def _init_git_repo(repo_path: Path) -> None:
    """Initialize a real git repository with an initial commit in tmp_path."""
    subprocess.run(["git", "init"], cwd=str(repo_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo_path), check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=str(repo_path), check=True
    )
    readme = repo_path / "README.md"
    readme.write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo_path), check=True)
    subprocess.run(
        ["git", "commit", "-m", "chore: initial commit"],
        cwd=str(repo_path),
        check=True,
    )


class LocalGitWorktreeManager:
    """Context manager executing real git worktree operations for isolated testing."""

    _git_add_lock: Optional[asyncio.Lock] = None
    _git_remove_lock: Optional[asyncio.Lock] = None

    @classmethod
    def get_add_lock(cls) -> asyncio.Lock:
        if cls._git_add_lock is None:
            cls._git_add_lock = asyncio.Lock()
        return cls._git_add_lock

    @classmethod
    def get_remove_lock(cls) -> asyncio.Lock:
        if cls._git_remove_lock is None:
            cls._git_remove_lock = asyncio.Lock()
        return cls._git_remove_lock

    @classmethod
    def reset_locks(cls) -> None:
        cls._git_add_lock = None
        cls._git_remove_lock = None

    def __init__(self, task_id: str, repo_root: Path):
        self.task_id = task_id
        self.repo_root = repo_root
        self.worktree_path = repo_root / ".worktrees" / "agent" / task_id
        self.branch_name = f"agent/{task_id}"

    async def __aenter__(self) -> Path:
        async with self.get_add_lock():
            self.worktree_path.parent.mkdir(parents=True, exist_ok=True)
            cmd = [
                "git",
                "worktree",
                "add",
                "-b",
                self.branch_name,
                str(self.worktree_path),
                "HEAD",
            ]
            await asyncio.to_thread(
                subprocess.run,
                cmd,
                cwd=str(self.repo_root),
                capture_output=True,
                check=True,
            )
        return self.worktree_path

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        async with self.get_remove_lock():
            cmd = ["git", "worktree", "remove", "--force", str(self.worktree_path)]
            await asyncio.to_thread(
                subprocess.run,
                cmd,
                cwd=str(self.repo_root),
                capture_output=True,
                check=False,
            )
            branch_del = ["git", "branch", "-D", self.branch_name]
            await asyncio.to_thread(
                subprocess.run,
                branch_del,
                cwd=str(self.repo_root),
                capture_output=True,
                check=False,
            )


@pytest.mark.asyncio
async def test_parallel_worktree_lifecycle_in_tmp_git(tmp_path: Path):
    """Test 3 tasks can concurrently provision isolated worktrees in a real git repository."""
    LocalGitWorktreeManager.reset_locks()
    _init_git_repo(tmp_path)

    active_worktrees: list[Path] = []
    max_active = 0
    lock = asyncio.Lock()

    async def run_worker_in_worktree(task_id: str):
        nonlocal max_active
        async with LocalGitWorktreeManager(task_id=task_id, repo_root=tmp_path) as wt_path:
            async with lock:
                active_worktrees.append(wt_path)
                if len(active_worktrees) > max_active:
                    max_active = len(active_worktrees)

            assert wt_path.exists()
            assert (wt_path / ".git").exists()
            # Simulate worker modifying a file in its isolated worktree
            task_file = wt_path / f"{task_id}.txt"
            task_file.write_text(f"Output of {task_id}", encoding="utf-8")

            # Sufficient sleep window to ensure concurrent overlap across thread transitions
            await asyncio.sleep(0.5)

            async with lock:
                active_worktrees.remove(wt_path)

    # Concurrently execute 3 worktrees
    await asyncio.gather(
        run_worker_in_worktree("task_1"),
        run_worker_in_worktree("task_2"),
        run_worker_in_worktree("task_3"),
    )

    assert max_active >= 2
    # After exit, worktrees must be cleanly removed
    assert not (tmp_path / ".worktrees" / "agent" / "task_1").exists()
    assert not (tmp_path / ".worktrees" / "agent" / "task_2").exists()
    assert not (tmp_path / ".worktrees" / "agent" / "task_3").exists()


@pytest.mark.asyncio
async def test_parallel_orchestrator_execution_with_worktree_manager(tmp_path: Path, monkeypatch):
    """Run orchestrator with max_workers=3 and verify 3 parallel tasks complete cleanly."""
    LocalGitWorktreeManager.reset_locks()
    _init_git_repo(tmp_path)

    plan = OrchestrationPlan(
        plan_id="plan_parallel_3tasks",
        goal="Execute 3 parallel tasks with worktree isolation",
        parallel_config=ParallelExecutionConfig(
            max_workers=3,
            worktree_base_dir=".worktrees/agent",
            enable_contract_freeze=False,
        ),
        tasks=[
            SubTask(
                id="task_1",
                name="Task 1",
                role=AgentRole.CODER,
                instruction="Build component 1",
            ),
            SubTask(
                id="task_2",
                name="Task 2",
                role=AgentRole.CODER,
                instruction="Build component 2",
            ),
            SubTask(
                id="task_3",
                name="Task 3",
                role=AgentRole.CODER,
                instruction="Build component 3",
            ),
        ],
    )

    executed_tasks = []
    concurrency_counter = 0
    max_concurrency = 0
    lock = asyncio.Lock()

    async def mock_execute_subtask(plan, subtask, task_results=None, workspace_dir=None):
        nonlocal concurrency_counter, max_concurrency
        # Provision isolated worktree via real git operations in tmp_path
        async with LocalGitWorktreeManager(
            task_id=subtask.id,
            repo_root=tmp_path,
        ) as wt_path:
            async with lock:
                concurrency_counter += 1
                if concurrency_counter > max_concurrency:
                    max_concurrency = concurrency_counter
                executed_tasks.append(subtask.id)

            assert wt_path.exists()
            assert (wt_path / ".git").exists()
            out_file = wt_path / f"result_{subtask.id}.txt"
            out_file.write_text(f"Done {subtask.id}", encoding="utf-8")

            # Sufficient sleep window to ensure concurrent overlap across thread transitions
            await asyncio.sleep(0.5)

            async with lock:
                concurrency_counter -= 1

            return RunResult(
                task_id=subtask.id,
                success=True,
                exit_code=0,
                duration_seconds=0.5,
                output_text=f"Completed {subtask.id}",
            )

    orchestrator = AgentOrchestrator()
    monkeypatch.setattr(orchestrator, "execute_subtask", mock_execute_subtask)

    plan_file = tmp_path / "plan.yaml"
    plan_file.write_text("plan_id: plan_parallel_3tasks\n", encoding="utf-8")

    result = await orchestrator.run_plan_parallel(
        plan=plan,
        max_workers=3,
        plan_file=str(plan_file),
    )

    assert result.success is True
    assert result.total_tasks == 3
    assert result.completed_tasks == 3
    assert result.task_statuses["task_1"] == TaskStatus.COMPLETED
    assert result.task_statuses["task_2"] == TaskStatus.COMPLETED
    assert result.task_statuses["task_3"] == TaskStatus.COMPLETED
    assert max_concurrency >= 2

    # Verify worktrees are torn down without conflict
    for tid in ["task_1", "task_2", "task_3"]:
        wt_dir = tmp_path / ".worktrees" / "agent" / tid
        assert not wt_dir.exists()
