"""Unit tests for AgentOrchestrator."""

from unittest.mock import AsyncMock

import pytest

from harness_agent.models import (
    AgentRole,
    AgyConfig,
    OrchestrationPlan,
    RunResult,
    SubTask,
    TaskStatus,
)
from harness_agent.orchestrator import AgentOrchestrator


def test_resolve_execution_order_dag():
    tasks = [
        SubTask(id="task_c", name="Task C", instruction="Deploy", depends_on=["task_b"]),
        SubTask(id="task_a", name="Task A", instruction="Research"),
        SubTask(id="task_b", name="Task B", instruction="Build", depends_on=["task_a"]),
    ]

    orchestrator = AgentOrchestrator()
    ordered = orchestrator.resolve_execution_order(tasks)

    ordered_ids = [t.id for t in ordered]
    assert ordered_ids == ["task_a", "task_b", "task_c"]


def test_resolve_execution_order_cycle_detected():
    tasks = [
        SubTask(id="task_1", name="Task 1", instruction="One", depends_on=["task_2"]),
        SubTask(id="task_2", name="Task 2", instruction="Two", depends_on=["task_1"]),
    ]

    orchestrator = AgentOrchestrator()
    with pytest.raises(ValueError, match="Cyclic dependency detected"):
        orchestrator.resolve_execution_order(tasks)


@pytest.mark.asyncio
async def test_run_plan_success(monkeypatch):
    plan = OrchestrationPlan(
        plan_id="plan_1",
        goal="Build feature and verify",
        tasks=[
            SubTask(id="code", name="Code", role=AgentRole.CODER, instruction="Write code"),
            SubTask(
                id="test",
                name="Test",
                role=AgentRole.TESTER,
                instruction="Run tests",
                depends_on=["code"],
            ),
        ],
    )

    mock_runner = AsyncMock()
    mock_runner.execute_task.side_effect = [
        RunResult(
            task_id="code",
            success=True,
            exit_code=0,
            duration_seconds=1.0,
            output_text="Code written successfully.",
        ),
        RunResult(
            task_id="test",
            success=True,
            exit_code=0,
            duration_seconds=0.8,
            output_text="All 5 tests passed.",
        ),
    ]

    orchestrator = AgentOrchestrator(base_config=AgyConfig())
    # Monkeypatch execute_subtask or AgyRunner execute_task
    monkeypatch.setattr(
        "harness_agent.orchestrator.AgyRunner.execute_task", mock_runner.execute_task
    )

    result = await orchestrator.run_plan(plan)

    assert result.success is True
    assert result.total_tasks == 2
    assert result.completed_tasks == 2
    assert result.failed_tasks == 0
    assert result.task_statuses["code"] == TaskStatus.COMPLETED
    assert result.task_statuses["test"] == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_run_plan_dependency_failure_blocks_downstream(monkeypatch):
    plan = OrchestrationPlan(
        plan_id="plan_fail",
        goal="Handle failures",
        tasks=[
            SubTask(id="step_1", name="Step 1", role=AgentRole.CODER, instruction="Fail here"),
            SubTask(
                id="step_2",
                name="Step 2",
                role=AgentRole.TESTER,
                instruction="Should not run",
                depends_on=["step_1"],
            ),
        ],
        stop_on_failure=True,
    )

    mock_runner = AsyncMock()
    mock_runner.execute_task.return_value = RunResult(
        task_id="step_1",
        success=False,
        exit_code=1,
        duration_seconds=0.5,
        error_message="Syntax error encountered",
    )

    monkeypatch.setattr(
        "harness_agent.orchestrator.AgyRunner.execute_task", mock_runner.execute_task
    )

    orchestrator = AgentOrchestrator()
    result = await orchestrator.run_plan(plan)

    assert result.success is False
    assert result.completed_tasks == 0
    assert result.failed_tasks >= 1
    assert result.task_statuses["step_1"] == TaskStatus.FAILED
    assert result.task_statuses["step_2"] in [TaskStatus.BLOCKED, TaskStatus.SKIPPED]


def test_load_and_save_plan(tmp_path):
    yaml_content = """
plan_id: "plan_test_io"
goal: "Test loading and saving"
tasks:
  - id: "t1"
    name: "Task 1"
    role: "coder"
    instruction: "Do task 1"
"""
    plan_file = tmp_path / "plan.yaml"
    plan_file.write_text(yaml_content, encoding="utf-8")

    orchestrator = AgentOrchestrator()
    plan = orchestrator.load_plan_from_yaml(str(plan_file))
    assert plan.plan_id == "plan_test_io"
    assert len(plan.tasks) == 1
    assert plan.tasks[0].role == AgentRole.CODER
    assert plan.tasks[0].plan_id == "plan_test_io"


def test_load_plan_from_markdown_frontmatter(tmp_path):
    md_content = """---
plan_id: "plan_markdown_test"
goal: "Test markdown plan with frontmatter"
tasks:
  - id: "subtask_01"
    name: "Subtask 01"
    role: "coder"
    instruction: "Implement feature"
---

# Plan: Markdown Test
Details about this plan.
"""
    plan_file = tmp_path / "main_plan_markdown_test.md"
    plan_file.write_text(md_content, encoding="utf-8")

    orchestrator = AgentOrchestrator()
    plan = orchestrator.load_plan(str(plan_file))
    assert plan.plan_id == "plan_markdown_test"
    assert plan.goal == "Test markdown plan with frontmatter"
    assert plan.tasks[0].plan_id == "plan_markdown_test"


def test_load_plan_missing_plan_id_raises(tmp_path):
    invalid_yaml = """
goal: "Missing plan id"
tasks:
  - id: "t1"
    name: "Task 1"
    role: "coder"
    instruction: "Do task 1"
"""
    plan_file = tmp_path / "invalid_plan.yaml"
    plan_file.write_text(invalid_yaml, encoding="utf-8")

    orchestrator = AgentOrchestrator()
    with pytest.raises(ValueError, match="missing mandatory 'plan_id'"):
        orchestrator.load_plan(str(plan_file))
