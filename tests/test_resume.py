"""Tests for DAG state persistence and resume capability."""

from unittest.mock import AsyncMock

import pytest
from click.testing import CliRunner

from harness_agent.cli import main
from harness_agent.models import (
    AgentRole,
    AgyConfig,
    OrchestrationPlan,
    RunResult,
    SubTask,
    TaskStatus,
)
from harness_agent.orchestrator import AgentOrchestrator
from harness_agent.state import DAGStateStore


@pytest.fixture
def temp_db(tmp_path):
    """Provide a temporary SQLite state DB path."""
    return str(tmp_path / "test_state.db")


@pytest.mark.asyncio
async def test_simulate_shutdown_and_resume(temp_db, monkeypatch):
    """Simulate Orchestrator shutdown while Task 2 is RUNNING.

    Restart via resume and verify it picks up Task 2 without restarting Task 1
    (which was COMPLETED).
    """
    plan = OrchestrationPlan(
        plan_id="plan_shutdown_sim",
        goal="Test crash and resume capability",
        tasks=[
            SubTask(id="task_1", name="Task 1", role=AgentRole.CODER, instruction="Do 1"),
            SubTask(
                id="task_2",
                name="Task 2",
                role=AgentRole.CODER,
                instruction="Do 2",
                depends_on=["task_1"],
            ),
            SubTask(
                id="task_3",
                name="Task 3",
                role=AgentRole.TESTER,
                instruction="Do 3",
                depends_on=["task_2"],
            ),
        ],
    )

    state_store = DAGStateStore(db_path=temp_db)
    orchestrator = AgentOrchestrator(
        base_config=AgyConfig(),
        state_store=state_store,
    )

    # Phase 1: Task 1 succeeds, Task 2 crashes/halts during execution
    executed_task_ids = []

    async def mock_execute_phase1(self, task_def):
        executed_task_ids.append(task_def.id)
        if task_def.id == "task_1":
            return RunResult(
                task_id="task_1",
                success=True,
                exit_code=0,
                duration_seconds=0.5,
                output_text="Task 1 done",
            )
        elif task_def.id == "task_2":
            # Simulate sudden crash/abort during execution of Task 2
            raise SystemExit("Simulated process crash while Task 2 is RUNNING")

    monkeypatch.setattr(
        "harness_agent.orchestrator.AgyRunner.execute_task",
        mock_execute_phase1,
    )

    with pytest.raises(SystemExit, match="Simulated process crash"):
        await orchestrator.run_plan(plan)

    # Verify Phase 1 persistence state on disk
    saved_state = state_store.load_run_state("plan_shutdown_sim")
    assert saved_state is not None
    assert saved_state["task_statuses"]["task_1"] == TaskStatus.COMPLETED
    assert saved_state["task_statuses"]["task_2"] == TaskStatus.RUNNING
    assert saved_state["task_statuses"]["task_3"] == TaskStatus.PENDING

    # Phase 2: Resume execution
    resume_executed_ids = []

    async def mock_execute_phase2(self, task_def):
        resume_executed_ids.append(task_def.id)
        return RunResult(
            task_id=task_def.id,
            success=True,
            exit_code=0,
            duration_seconds=0.4,
            output_text=f"{task_def.id} completed on resume",
        )

    monkeypatch.setattr(
        "harness_agent.orchestrator.AgyRunner.execute_task",
        mock_execute_phase2,
    )

    resume_orchestrator = AgentOrchestrator(
        base_config=AgyConfig(),
        state_store=state_store,
    )
    result = await resume_orchestrator.resume_plan("plan_shutdown_sim")

    # CRITICAL CHECK: Task 1 must NOT have been restarted!
    assert "task_1" not in resume_executed_ids, "Task 1 was already COMPLETED and must not restart!"
    # Task 2 and Task 3 must have executed
    assert resume_executed_ids == ["task_2", "task_3"]

    assert result.success is True
    assert result.total_tasks == 3
    assert result.completed_tasks == 3
    assert result.failed_tasks == 0
    assert result.task_statuses["task_1"] == TaskStatus.COMPLETED
    assert result.task_statuses["task_2"] == TaskStatus.COMPLETED
    assert result.task_statuses["task_3"] == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_continuous_serialization_lifecycle(temp_db, monkeypatch):
    """Verify that every lifecycle state is persisted to disk."""
    plan = OrchestrationPlan(
        plan_id="plan_lifecycle",
        goal="Verify continuous serialization",
        tasks=[
            SubTask(id="sub_a", name="Sub A", role=AgentRole.CODER, instruction="Do A"),
        ],
    )

    state_store = DAGStateStore(db_path=temp_db)
    observed_states = []

    original_update = state_store.update_task_status

    def spy_update_task_status(plan_id, task_id, status, **kwargs):
        observed_states.append((task_id, status))
        return original_update(plan_id, task_id, status, **kwargs)

    monkeypatch.setattr(state_store, "update_task_status", spy_update_task_status)

    mock_runner = AsyncMock()
    mock_runner.execute_task.return_value = RunResult(
        task_id="sub_a",
        success=True,
        exit_code=0,
        duration_seconds=0.2,
    )
    monkeypatch.setattr(
        "harness_agent.orchestrator.AgyRunner.execute_task",
        mock_runner.execute_task,
    )

    orchestrator = AgentOrchestrator(state_store=state_store)
    result = await orchestrator.run_plan(plan)

    assert result.success is True
    # Check that RUNNING -> VALIDATING -> COMPLETED occurred in order
    statuses_only = [st for tid, st in observed_states if tid == "sub_a"]
    assert TaskStatus.RUNNING in statuses_only
    assert TaskStatus.VALIDATING in statuses_only
    assert TaskStatus.COMPLETED in statuses_only

    running_idx = statuses_only.index(TaskStatus.RUNNING)
    validating_idx = statuses_only.index(TaskStatus.VALIDATING)
    completed_idx = statuses_only.index(TaskStatus.COMPLETED)
    assert running_idx < validating_idx < completed_idx


def test_markdown_plan_sync_and_load(tmp_path):
    """Verify loading from markdown with frontmatter and synchronizing status block."""
    md_content = """---
plan_id: "plan_markdown_test"
goal: "Implement PoC via markdown"
tasks:
  - id: "poc_1"
    name: "PoC Task 1"
    role: "coder"
    instruction: "Generate data"
  - id: "poc_2"
    name: "PoC Task 2"
    role: "tester"
    instruction: "Verify data"
    depends_on: ["poc_1"]
---
# Main 1-Day PoC Plan
Some documentation here.
"""
    plan_file = tmp_path / "main_poc.md"
    plan_file.write_text(md_content, encoding="utf-8")

    db_path = str(tmp_path / "state.db")
    state_store = DAGStateStore(db_path=db_path)
    orchestrator = AgentOrchestrator(state_store=state_store)

    plan = orchestrator.load_plan(str(plan_file))
    assert plan.plan_id == "plan_markdown_test"
    assert len(plan.tasks) == 2

    # Update markdown with status
    statuses = {
        "poc_1": TaskStatus.COMPLETED,
        "poc_2": TaskStatus.RUNNING,
    }
    DAGStateStore.update_markdown_status(str(plan_file), statuses, goal=plan.goal)

    updated_text = plan_file.read_text(encoding="utf-8")
    assert "<!-- DAG_STATUS_START -->" in updated_text
    assert "## Task DAG Execution Status" in updated_text
    assert "`poc_1`" in updated_text
    assert "COMPLETED" in updated_text
    assert "`poc_2`" in updated_text
    assert "RUNNING" in updated_text
    assert "<!-- DAG_STATUS_END -->" in updated_text


def test_cli_resume_command(tmp_path, monkeypatch):
    """Test CLI commands: 'harness-agent resume' and 'harness-agent run resume'."""
    yaml_content = """
plan_id: "cli_plan"
goal: "Test CLI resume"
tasks:
  - id: "step_1"
    name: "Step 1"
    role: "coder"
    instruction: "Do step 1"
"""
    plan_file = tmp_path / "cli_plan.yaml"
    plan_file.write_text(yaml_content, encoding="utf-8")
    db_file = str(tmp_path / "cli_state.db")

    # Mock runner execute_task
    mock_runner = AsyncMock()
    mock_runner.execute_task.return_value = RunResult(
        task_id="step_1",
        success=True,
        exit_code=0,
        duration_seconds=0.1,
        output_text="Step 1 success",
    )
    monkeypatch.setattr(
        "harness_agent.orchestrator.AgyRunner.execute_task",
        mock_runner.execute_task,
    )

    runner = CliRunner()

    # 1. First run with orchestrate
    res_orch = runner.invoke(
        main,
        ["orchestrate", str(plan_file), "--db", db_file],
    )
    assert res_orch.exit_code == 0
    assert "Orchestration Summary" in res_orch.output

    # 2. Test 'harness-agent run resume'
    res_run_resume = runner.invoke(
        main,
        ["run", "resume", str(plan_file), "--db", db_file],
    )
    assert res_run_resume.exit_code == 0
    assert "Resuming orchestration run" in res_run_resume.output

    # 3. Test 'harness-agent resume'
    res_resume = runner.invoke(
        main,
        ["resume", str(plan_file), "--db", db_file],
    )
    assert res_resume.exit_code == 0
    assert "Resuming orchestration run" in res_resume.output


@pytest.mark.asyncio
async def test_resume_nonexistent_plan_raises(temp_db):
    """Resuming when no state exists raises a helpful ValueError."""
    orchestrator = AgentOrchestrator(state_store=DAGStateStore(db_path=temp_db))
    with pytest.raises(ValueError, match="No saved orchestration run found"):
        await orchestrator.resume_plan("non_existent_plan")
