"""Layer 1 Unit tests for Async DAG scheduler and in-degree topological resolution."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from harness_agent.core.models import (
    AgentRole,
    OrchestrationPlan,
    ParallelExecutionConfig,
    RunResult,
    SubTask,
)
from harness_agent.core.orchestrator import AgentOrchestrator


def test_dag_indegree_and_topological_resolution():
    """Verify in-degree computation and topological dependency ordering."""
    tasks = [
        SubTask(id="task_c", name="Task C", instruction="Deploy", depends_on=["task_b"]),
        SubTask(id="task_a", name="Task A", instruction="Research"),
        SubTask(id="task_b", name="Task B", instruction="Build", depends_on=["task_a"]),
    ]

    orchestrator = AgentOrchestrator()
    ordered = orchestrator.resolve_execution_order(tasks)

    ordered_ids = [t.id for t in ordered]
    assert ordered_ids == ["task_a", "task_b", "task_c"]


def test_dag_cycle_detection():
    """Verify cyclic dependencies raise ValueError."""
    tasks = [
        SubTask(id="task_1", name="Task 1", instruction="One", depends_on=["task_2"]),
        SubTask(id="task_2", name="Task 2", instruction="Two", depends_on=["task_1"]),
    ]

    orchestrator = AgentOrchestrator()
    with pytest.raises(ValueError, match="Cyclic dependency detected"):
        orchestrator.resolve_execution_order(tasks)


@pytest.mark.asyncio
async def test_async_dag_scheduler_concurrency_throttling(monkeypatch):
    """Test AsyncDAGScheduler concurrency is throttled to max_workers limit (max 3)."""
    current_concurrent = 0
    max_observed_concurrent = 0
    lock = asyncio.Lock()

    async def mock_execute_task(task_def):
        nonlocal current_concurrent, max_observed_concurrent
        async with lock:
            current_concurrent += 1
            if current_concurrent > max_observed_concurrent:
                max_observed_concurrent = current_concurrent

        # Simulate async worker execution time
        await asyncio.sleep(0.05)

        async with lock:
            current_concurrent -= 1

        return RunResult(
            task_id=task_def.id,
            success=True,
            exit_code=0,
            duration_seconds=0.05,
            output_text=f"Completed {task_def.id}",
        )

    mock_runner = AsyncMock()
    mock_runner.execute_task.side_effect = mock_execute_task

    monkeypatch.setattr(
        "harness_agent.core.orchestrator.AgyRunner.execute_task",
        mock_runner.execute_task,
    )

    # 6 independent tasks that can all execute in parallel
    tasks = [
        SubTask(id=f"task_{i}", name=f"Task {i}", role=AgentRole.CODER, instruction=f"Run {i}")
        for i in range(6)
    ]

    plan = OrchestrationPlan(
        plan_id="plan_concurrency_test",
        goal="Verify concurrency throttle",
        parallel_config=ParallelExecutionConfig(max_workers=3, enable_contract_freeze=False),
        tasks=tasks,
    )

    orchestrator = AgentOrchestrator()
    result = await orchestrator.run_plan_parallel(plan, max_workers=3)

    assert result.success is True
    assert result.total_tasks == 6
    assert result.completed_tasks == 6
    assert max_observed_concurrent <= 3
    assert max_observed_concurrent >= 2


@pytest.mark.asyncio
async def test_async_dag_scheduler_parallel_diamond_execution(monkeypatch):
    """Test diamond DAG executes independent parallel branches concurrently."""
    execution_order = []
    lock = asyncio.Lock()

    async def mock_execute_task(task_def):
        async with lock:
            execution_order.append(f"start_{task_def.id}")

        await asyncio.sleep(0.04)

        async with lock:
            execution_order.append(f"end_{task_def.id}")

        return RunResult(
            task_id=task_def.id,
            success=True,
            exit_code=0,
            duration_seconds=0.04,
            output_text=f"Done {task_def.id}",
        )

    mock_runner = AsyncMock()
    mock_runner.execute_task.side_effect = mock_execute_task

    monkeypatch.setattr(
        "harness_agent.core.orchestrator.AgyRunner.execute_task",
        mock_runner.execute_task,
    )

    # Diamond: task_root -> (branch_1, branch_2) -> task_join
    tasks = [
        SubTask(id="task_root", name="Root", role=AgentRole.CODER, instruction="Root"),
        SubTask(
            id="branch_1",
            name="Branch 1",
            role=AgentRole.CODER,
            instruction="B1",
            depends_on=["task_root"],
        ),
        SubTask(
            id="branch_2",
            name="Branch 2",
            role=AgentRole.CODER,
            instruction="B2",
            depends_on=["task_root"],
        ),
        SubTask(
            id="task_join",
            name="Join",
            role=AgentRole.TESTER,
            instruction="Join",
            depends_on=["branch_1", "branch_2"],
        ),
    ]

    plan = OrchestrationPlan(
        plan_id="plan_diamond_test",
        goal="Verify diamond execution",
        parallel_config=ParallelExecutionConfig(max_workers=3, enable_contract_freeze=False),
        tasks=tasks,
    )

    orchestrator = AgentOrchestrator()
    result = await orchestrator.run_plan_parallel(plan, max_workers=3)

    assert result.success is True
    assert result.completed_tasks == 4
    # Root must start and finish before branches start
    assert execution_order[0] == "start_task_root"
    assert execution_order[1] == "end_task_root"
    # Join must finish last
    assert execution_order[-1] == "end_task_join"
