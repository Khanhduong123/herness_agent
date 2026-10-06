"""Unit tests for DAGStateStore and OrchestrationRunRecord using SQLModel."""

import time
from pathlib import Path

from sqlmodel import Session, select

from harness_agent.core.models import AgentRole, OrchestrationPlan, RunResult, SubTask, TaskStatus
from harness_agent.core.state import DAGStateStore, OrchestrationRunRecord


def _create_sample_plan(
    plan_id: str = "plan_test_01", goal: str = "Test SQLModel State Store"
) -> OrchestrationPlan:
    return OrchestrationPlan(
        plan_id=plan_id,
        goal=goal,
        tasks=[
            SubTask(
                id="task_1",
                name="Task 1",
                role=AgentRole.CODER,
                instruction="Implement feature",
            ),
            SubTask(
                id="task_2",
                name="Task 2",
                role=AgentRole.TESTER,
                instruction="Run unit tests",
                depends_on=["task_1"],
            ),
        ],
    )


def _create_sample_result(task_id: str, success: bool = True, output_text: str = "") -> RunResult:
    return RunResult(
        task_id=task_id,
        success=success,
        exit_code=0 if success else 1,
        duration_seconds=1.23,
        output_text=output_text,
    )


def test_state_store_init_and_schema_creation(tmp_path: Path):
    db_file = tmp_path / "subdir" / "test_state.db"
    assert not db_file.exists()

    store = DAGStateStore(db_path=str(db_file))

    assert db_file.exists()
    assert store.engine is not None

    # Verify table exists in SQLite database via SQLModel session
    with Session(store.engine) as session:
        records = session.exec(select(OrchestrationRunRecord)).all()
        assert len(records) == 0


def test_save_run_state_insert(tmp_path: Path):
    db_file = tmp_path / "test_state.db"
    store = DAGStateStore(db_path=str(db_file))

    plan = _create_sample_plan("plan_insert_01")
    task_statuses = {
        "task_1": TaskStatus.RUNNING,
        "task_2": TaskStatus.PENDING,
    }
    task_results = {
        "task_1": _create_sample_result("task_1", success=True, output_text="In progress"),
    }

    store.save_run_state(
        plan=plan,
        task_statuses=task_statuses,
        task_results=task_results,
        status="running",
        plan_file="sample_plan.md",
    )

    with Session(store.engine) as session:
        record = session.get(OrchestrationRunRecord, "plan_insert_01")
        assert record is not None
        assert record.plan_id == "plan_insert_01"
        assert record.goal == plan.goal
        assert record.status == "running"
        assert record.plan_file == "sample_plan.md"
        assert record.created_at > 0
        assert record.updated_at == record.created_at


def test_save_run_state_upsert_preserves_created_at(tmp_path: Path):
    db_file = tmp_path / "test_state.db"
    store = DAGStateStore(db_path=str(db_file))

    plan = _create_sample_plan("plan_upsert_01")
    store.save_run_state(
        plan=plan,
        task_statuses={"task_1": TaskStatus.RUNNING},
        task_results={},
        status="running",
        plan_file="old_plan.md",
    )

    loaded_initial = store.load_run_state("plan_upsert_01")
    assert loaded_initial is not None
    original_created_at = loaded_initial["created_at"]

    # Sleep briefly to ensure updated_at timestamp increments
    time.sleep(0.01)

    # Upsert with new status and tasks
    store.save_run_state(
        plan=plan,
        task_statuses={"task_1": TaskStatus.COMPLETED, "task_2": TaskStatus.RUNNING},
        task_results={"task_1": _create_sample_result("task_1", success=True)},
        status="running",
    )

    loaded_updated = store.load_run_state("plan_upsert_01")
    assert loaded_updated is not None
    assert loaded_updated["created_at"] == original_created_at
    assert loaded_updated["updated_at"] > original_created_at
    # plan_file was preserved from prior record since new plan_file was None
    assert loaded_updated["plan_file"] == "old_plan.md"
    assert loaded_updated["task_statuses"]["task_1"] == TaskStatus.COMPLETED
    assert loaded_updated["task_statuses"]["task_2"] == TaskStatus.RUNNING


def test_update_task_status(tmp_path: Path):
    db_file = tmp_path / "test_state.db"
    store = DAGStateStore(db_path=str(db_file))

    plan = _create_sample_plan("plan_task_update_01")
    store.save_run_state(
        plan=plan,
        task_statuses={"task_1": TaskStatus.RUNNING, "task_2": TaskStatus.PENDING},
        task_results={},
        status="running",
    )

    # Update task_1 to completed with result
    store.update_task_status(
        plan_id="plan_task_update_01",
        task_id="task_1",
        status=TaskStatus.COMPLETED,
        result=_create_sample_result("task_1", success=True, output_text="Task 1 done"),
    )

    state = store.load_run_state("plan_task_update_01")
    assert state is not None
    assert state["task_statuses"]["task_1"] == TaskStatus.COMPLETED
    assert state["task_statuses"]["task_2"] == TaskStatus.PENDING
    assert state["task_results"]["task_1"].success is True
    assert state["task_results"]["task_1"].output_text == "Task 1 done"

    # Update task_2 with overall_status
    store.update_task_status(
        plan_id="plan_task_update_01",
        task_id="task_2",
        status=TaskStatus.COMPLETED,
        result=_create_sample_result("task_2", success=True, output_text="Task 2 done"),
        overall_status="completed",
    )

    final_state = store.load_run_state("plan_task_update_01")
    assert final_state is not None
    assert final_state["status"] == "completed"
    assert final_state["task_statuses"]["task_2"] == TaskStatus.COMPLETED

    # Updating non-existent plan should return safely without error
    store.update_task_status(
        plan_id="non_existent_plan",
        task_id="task_1",
        status=TaskStatus.COMPLETED,
    )


def test_load_run_state_by_explicit_id_and_non_existent(tmp_path: Path):
    db_file = tmp_path / "test_state.db"
    store = DAGStateStore(db_path=str(db_file))

    # Empty store returns None
    assert store.load_run_state("unknown_plan") is None
    assert store.load_run_state() is None

    plan = _create_sample_plan("plan_lookup_01")
    store.save_run_state(
        plan=plan,
        task_statuses={"task_1": TaskStatus.COMPLETED},
        task_results={"task_1": _create_sample_result("task_1", success=True)},
        status="completed",
    )

    state = store.load_run_state("plan_lookup_01")
    assert state is not None
    assert state["plan_id"] == "plan_lookup_01"
    assert state["plan"].plan_id == "plan_lookup_01"
    assert state["goal"] == plan.goal
    assert state["status"] == "completed"

    # Non-existent still returns None
    assert store.load_run_state("does_not_exist") is None


def test_load_latest_active_run_state(tmp_path: Path):
    db_file = tmp_path / "test_state.db"
    store = DAGStateStore(db_path=str(db_file))

    plan1 = _create_sample_plan("plan_first")
    store.save_run_state(
        plan=plan1,
        task_statuses={"task_1": TaskStatus.COMPLETED},
        task_results={},
        status="completed",
    )

    time.sleep(0.01)

    plan2 = _create_sample_plan("plan_second")
    store.save_run_state(
        plan=plan2,
        task_statuses={"task_1": TaskStatus.RUNNING},
        task_results={},
        status="running",
    )

    # Calling without plan_id should load the latest updated run (plan_second)
    latest = store.load_run_state()
    assert latest is not None
    assert latest["plan_id"] == "plan_second"

    time.sleep(0.01)

    # If plan_first is updated, it becomes the latest
    store.update_task_status(
        plan_id="plan_first",
        task_id="task_2",
        status=TaskStatus.RUNNING,
    )
    latest_after_update = store.load_run_state()
    assert latest_after_update is not None
    assert latest_after_update["plan_id"] == "plan_first"


def test_list_runs_ordered_by_updated_at_desc(tmp_path: Path):
    db_file = tmp_path / "test_state.db"
    store = DAGStateStore(db_path=str(db_file))

    assert store.list_runs() == []

    plan_a = _create_sample_plan("plan_a")
    store.save_run_state(plan=plan_a, task_statuses={}, task_results={})

    time.sleep(0.01)
    plan_b = _create_sample_plan("plan_b")
    store.save_run_state(plan=plan_b, task_statuses={}, task_results={})

    time.sleep(0.01)
    plan_c = _create_sample_plan("plan_c")
    store.save_run_state(plan=plan_c, task_statuses={}, task_results={})

    runs = store.list_runs()
    assert len(runs) == 3
    assert [r["plan_id"] for r in runs] == ["plan_c", "plan_b", "plan_a"]

    # Updating plan_a puts it first
    time.sleep(0.01)
    store.save_run_state(plan=plan_a, task_statuses={}, task_results={})
    runs_after_update = store.list_runs()
    assert [r["plan_id"] for r in runs_after_update] == ["plan_a", "plan_c", "plan_b"]


def test_markdown_status_synchronization(tmp_path: Path):
    db_file = tmp_path / "test_state.db"
    md_file = tmp_path / "plan_doc.md"
    md_file.write_text("# My Plan Document\n\nSome initial text.\n", encoding="utf-8")

    store = DAGStateStore(db_path=str(db_file))
    plan = _create_sample_plan("plan_md_sync")

    store.save_run_state(
        plan=plan,
        task_statuses={"task_1": TaskStatus.RUNNING, "task_2": TaskStatus.PENDING},
        task_results={},
        plan_file=str(md_file),
    )

    content = md_file.read_text(encoding="utf-8")
    assert "<!-- DAG_STATUS_START -->" in content
    assert "<!-- DAG_STATUS_END -->" in content
    assert "`task_1` | RUNNING | [RUNNING]" in content
    assert "`task_2` | PENDING | [PENDING]" in content

    # Update task and verify markdown content replaces existing table cleanly
    store.update_task_status(
        plan_id="plan_md_sync",
        task_id="task_1",
        status=TaskStatus.COMPLETED,
    )

    updated_content = md_file.read_text(encoding="utf-8")
    assert updated_content.count("<!-- DAG_STATUS_START -->") == 1
    assert "`task_1` | COMPLETED | [COMPLETED]" in updated_content
