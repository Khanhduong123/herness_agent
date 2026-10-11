"""Unit tests for StateCoordinator and ReconciliationResult."""

from pathlib import Path

import pytest

from harness_agent.core.state import (
    AtomicSessionStore,
    EventWAL,
    ReconciliationResult,
    SessionState,
    StateCoordinator,
    WALEvent,
)


def test_tc01_clean_boot_matching_state(tmp_path: Path):
    """TC-01: Snapshot step 3, WAL step 3 -> consistent=True, recovery_action='none'."""
    session_file = tmp_path / "session.json"
    wal_file = tmp_path / "log.csv"

    state = SessionState(
        task_id="task_01",
        session_id="sess_123",
        goal="Clean boot test",
        active_step=3,
        status="active",
    )
    AtomicSessionStore.save_snapshot(state, session_file)

    wal = EventWAL(wal_file)
    wal.append_event(WALEvent(session_id="sess_123", step_index=1, event_type="step_completed"))
    wal.append_event(WALEvent(session_id="sess_123", step_index=2, event_type="step_completed"))
    wal.append_event(WALEvent(session_id="sess_123", step_index=3, event_type="step_completed"))

    coordinator = StateCoordinator(session_path=session_file, wal_path=wal_file)
    result = coordinator.reconcile_on_startup()

    assert isinstance(result, ReconciliationResult)
    assert result.consistent is True
    assert result.recovered_step == 3
    assert result.recovery_action == "none"
    assert result.reconciled_state is not None
    assert result.reconciled_state.active_step == 3
    assert len(result.uncommitted_events) == 0


def test_tc02_wal_ahead_of_snapshot(tmp_path: Path):
    """TC-02: Snapshot step 2, WAL step 3 -> advances snapshot to step 3, updates file."""
    session_file = tmp_path / "session.json"
    wal_file = tmp_path / "log.csv"

    state = SessionState(
        task_id="task_02",
        session_id="sess_456",
        goal="WAL ahead test",
        active_step=2,
        status="active",
    )
    AtomicSessionStore.save_snapshot(state, session_file)

    wal = EventWAL(wal_file)
    wal.append_event(WALEvent(session_id="sess_456", step_index=1, event_type="step_completed"))
    wal.append_event(WALEvent(session_id="sess_456", step_index=2, event_type="step_completed"))
    wal.append_event(WALEvent(session_id="sess_456", step_index=3, event_type="step_completed"))

    coordinator = StateCoordinator(session_path=session_file, wal_path=wal_file)
    result = coordinator.reconcile_on_startup()

    assert result.consistent is True
    assert result.recovered_step == 3
    assert result.recovery_action == "advanced_to_wal"
    assert result.reconciled_state is not None
    assert result.reconciled_state.active_step == 3
    assert len(result.uncommitted_events) == 1
    assert result.uncommitted_events[0].step_index == 3

    # Check updated on disk
    persisted = AtomicSessionStore.load_snapshot(session_file)
    assert persisted is not None
    assert persisted.active_step == 3


def test_tc03_missing_snapshot_file_reconstruction(tmp_path: Path):
    """TC-03: Missing snapshot file, WAL has events -> reconstructs snapshot from WAL."""
    session_file = tmp_path / "session.json"
    wal_file = tmp_path / "log.csv"

    wal = EventWAL(wal_file)
    for i in range(1, 6):
        wal.append_event(
            WALEvent(
                session_id="sess_recon",
                step_index=i,
                event_type="step_finished",
            )
        )

    assert not session_file.exists()

    coordinator = StateCoordinator(session_path=session_file, wal_path=wal_file)
    result = coordinator.reconcile_on_startup()

    assert result.consistent is True
    assert result.recovered_step == 5
    assert result.recovery_action == "replayed_from_log"
    assert result.reconciled_state is not None
    assert result.reconciled_state.active_step == 5
    assert result.reconciled_state.session_id == "sess_recon"

    # Assert session.json was created on disk
    assert session_file.exists()
    disk_snapshot = AtomicSessionStore.load_snapshot(session_file)
    assert disk_snapshot is not None
    assert disk_snapshot.active_step == 5


def test_tc04_incomplete_action_crash(tmp_path: Path):
    """TC-04: Incomplete action crash -> WAL ending in action_start."""
    session_file = tmp_path / "session.json"
    wal_file = tmp_path / "log.csv"

    state = SessionState(
        task_id="task_04",
        session_id="sess_crash",
        goal="Action crash test",
        active_step=2,
    )
    AtomicSessionStore.save_snapshot(state, session_file)

    wal = EventWAL(wal_file)
    wal.append_event(WALEvent(session_id="sess_crash", step_index=1, event_type="step_done"))
    wal.append_event(WALEvent(session_id="sess_crash", step_index=2, event_type="action_start"))

    coordinator = StateCoordinator(session_path=session_file, wal_path=wal_file)
    result = coordinator.reconcile_on_startup()

    assert result.consistent is False
    assert result.recovered_step == 2
    assert result.recovery_action == "interrupted_action_detected"
    assert len(result.uncommitted_events) == 1
    assert result.uncommitted_events[0].event_type == "action_start"


def test_edge_case_fresh_run(tmp_path: Path):
    """Edge Case 1: Fresh run with both snapshot and WAL empty."""
    session_file = tmp_path / "session.json"
    wal_file = tmp_path / "log.csv"

    coordinator = StateCoordinator(session_path=session_file, wal_path=wal_file)
    result = coordinator.reconcile_on_startup()

    assert result.consistent is True
    assert result.recovered_step == 0
    assert result.recovery_action == "fresh_init"
    assert result.reconciled_state is None
    assert result.uncommitted_events == []


def test_edge_case_snapshot_missing_wal_10_steps(tmp_path: Path):
    """Edge Case 2: Snapshot missing but WAL has 10 steps -> replayed_from_log, step 10."""
    session_file = tmp_path / "session.json"
    wal_file = tmp_path / "log.csv"

    wal = EventWAL(wal_file)
    for i in range(1, 11):
        wal.append_event(
            WALEvent(
                session_id="sess_10",
                step_index=i,
                event_type="step_end",
            )
        )

    coordinator = StateCoordinator(session_path=session_file, wal_path=wal_file)
    result = coordinator.reconcile_on_startup()

    assert result.consistent is True
    assert result.recovered_step == 10
    assert result.reconciled_state is not None
    assert result.reconciled_state.active_step == 10
    assert result.recovery_action == "replayed_from_log"


def test_edge_case_trailing_error_in_wal(tmp_path: Path):
    """Edge Case 3: Trailing Error in WAL (status_code != 0) -> error_detected."""
    session_file = tmp_path / "session.json"
    wal_file = tmp_path / "log.csv"

    state = SessionState(
        task_id="task_err",
        session_id="sess_err",
        goal="Trailing error test",
        active_step=4,
    )
    AtomicSessionStore.save_snapshot(state, session_file)

    wal = EventWAL(wal_file)
    wal.append_event(
        WALEvent(
            session_id="sess_err",
            step_index=4,
            event_type="tool_execution",
            status_code=1,
            error_message="Command failed with exit code 1",
        )
    )

    coordinator = StateCoordinator(session_path=session_file, wal_path=wal_file)
    result = coordinator.reconcile_on_startup()

    assert result.consistent is False
    assert result.recovered_step == 4
    assert result.recovery_action == "error_detected"
    assert len(result.uncommitted_events) == 1
    assert result.uncommitted_events[0].status_code == 1

    # Verify snapshot state updated to error
    persisted = AtomicSessionStore.load_snapshot(session_file)
    assert persisted is not None
    assert persisted.status == "error"


def test_edge_case_snapshot_ahead_of_wal(tmp_path: Path):
    """Edge Case 4: Snapshot ahead of WAL -> snapshot_ahead_of_wal."""
    session_file = tmp_path / "session.json"
    wal_file = tmp_path / "log.csv"

    state = SessionState(
        task_id="task_ahead",
        session_id="sess_ahead",
        goal="Snapshot ahead test",
        active_step=5,
    )
    AtomicSessionStore.save_snapshot(state, session_file)

    wal = EventWAL(wal_file)
    wal.append_event(WALEvent(session_id="sess_ahead", step_index=3, event_type="step_done"))

    coordinator = StateCoordinator(session_path=session_file, wal_path=wal_file)
    result = coordinator.reconcile_on_startup()

    assert result.consistent is True
    assert result.recovered_step == 5
    assert result.recovery_action == "snapshot_ahead_of_wal"
    assert result.reconciled_state is not None
    assert result.reconciled_state.active_step == 5


@pytest.mark.asyncio
async def test_orchestrator_resume_with_state_coordinator(tmp_path: Path):
    """Verify orchestrator resume_plan integrates with StateCoordinator."""
    from harness_agent.core.models import AgentRole, OrchestrationPlan, SubTask, TaskStatus
    from harness_agent.core.orchestrator import AgentOrchestrator
    from harness_agent.core.state import DAGStateStore

    db_file = tmp_path / "orch.db"
    session_file = tmp_path / "session.json"
    wal_file = tmp_path / "log.csv"

    state = SessionState(
        task_id="subtask_01",
        session_id="sess_orch",
        goal="Orch test",
        active_step=1,
    )
    AtomicSessionStore.save_snapshot(state, session_file)

    wal = EventWAL(wal_file)
    wal.append_event(WALEvent(session_id="sess_orch", step_index=1, event_type="step_completed"))

    plan = OrchestrationPlan(
        plan_id="plan_orch_test",
        goal="Test orchestrator resume integration",
        tasks=[
            SubTask(
                id="task_done",
                name="Task Done",
                role=AgentRole.CODER,
                instruction="Done task",
            )
        ],
    )
    store = DAGStateStore(db_path=str(db_file))
    store.save_run_state(
        plan=plan,
        task_statuses={"task_done": TaskStatus.COMPLETED},
        task_results={},
        status="completed",
    )

    orch = AgentOrchestrator(state_store=store, db_path=str(db_file))
    res = await orch.resume_plan(
        plan_or_id="plan_orch_test",
        session_path=str(session_file),
        wal_path=str(wal_file),
    )

    assert orch.state_coordinator is not None
    assert res.plan_id == "plan_orch_test"
