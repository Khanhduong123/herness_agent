"""Unit tests for context persistence and rehydration.

Tests covering:
1. Auto-creation of .ai/context directory during orchestrator initialization.
2. Append-only WAL logging and secret redaction in wal_actions.log.
3. Atomic state snapshot write and reload for state.json.
4. Markdown compilation of context via compile_context_markdown and sync_context_markdown.
5. Rehydration and state recovery via StateCoordinator and dispatch prompt injection.
"""

import csv
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_agent.core.dispatch import HerdrDispatcher
from harness_agent.core.models import AgentRole, OrchestrationPlan, RunResult, SubTask
from harness_agent.core.orchestrator import AgentOrchestrator
from harness_agent.core.state import (
    DEFAULT_CONTEXT_MD_FILE,
    DEFAULT_STATE_SNAPSHOT_FILE,
    DEFAULT_WAL_ACTIONS_FILE,
    AtomicSessionStore,
    DAGStateStore,
    EventWAL,
    SessionState,
    StateCoordinator,
    WALEvent,
    compile_context_markdown,
    sync_context_markdown,
)

# =========================================================================
# 1. Auto-creation of .ai/context directory during orchestrator init
# =========================================================================


def test_orchestrator_initialization_creates_context_directory(tmp_path: Path):
    """Test that AgentOrchestrator initializes .ai/context directory and default coordinator."""
    orig_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        context_dir = tmp_path / ".ai" / "context"
        assert not context_dir.exists()

        orchestrator = AgentOrchestrator()

        assert context_dir.exists()
        assert context_dir.is_dir()
        assert orchestrator.state_coordinator is not None
        assert orchestrator.state_coordinator.session_path == Path(DEFAULT_STATE_SNAPSHOT_FILE)
        assert orchestrator.state_coordinator.wal_path == Path(DEFAULT_WAL_ACTIONS_FILE)
        assert orchestrator.state_coordinator.context_md_path == Path(DEFAULT_CONTEXT_MD_FILE)
    finally:
        os.chdir(orig_cwd)


def test_orchestrator_handles_context_directory_creation_failure():
    """Test graceful fallback when .ai/context creation encounters an OS error."""
    mock_store = MagicMock(spec=DAGStateStore)
    real_makedirs = os.makedirs

    def fake_makedirs(path, *args, **kwargs):
        if ".ai/context" in str(path) or ".ai\\context" in str(path):
            raise OSError("Permission denied")
        return real_makedirs(path, *args, **kwargs)

    with patch("os.makedirs", side_effect=fake_makedirs):
        orchestrator = AgentOrchestrator(state_store=mock_store)
        assert orchestrator.state_coordinator is None


# =========================================================================
# 2. Append-only WAL logging and secret redaction in wal_actions.log
# =========================================================================


def test_wal_initialization_header(tmp_path: Path):
    """Test EventWAL creates header on init and does not re-write header if file has content."""
    wal_file = tmp_path / ".ai" / "context" / "wal_actions.log"
    wal = EventWAL(wal_file)
    assert wal.wal_path.exists()

    with open(wal_file, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert len(reader) == 1
        assert reader[0] == EventWAL.CSV_HEADER

    # Re-instantiating on existing file should preserve it
    wal2 = EventWAL(wal_file)
    assert wal2.wal_path.exists()
    with open(wal_file, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert len(reader) == 1


def test_wal_append_events(tmp_path: Path):
    """Test appending multiple WAL events sequentially."""
    wal_file = tmp_path / "wal_actions.log"
    wal = EventWAL(wal_file)

    ev1 = WALEvent(
        session_id="session_1",
        step_index=1,
        event_type="subtask_start",
        tool_name="task_01",
    )
    ev2 = WALEvent(
        session_id="session_1",
        step_index=1,
        event_type="subtask_end",
        tool_name="task_01",
        status_code=0,
        latency_ms=125.5,
    )
    wal.append_event(ev1)
    wal.append_event(ev2)

    events = wal.read_all_events()
    assert len(events) == 2
    assert events[0].session_id == "session_1"
    assert events[0].step_index == 1
    assert events[0].event_type == "subtask_start"
    assert events[0].tool_name == "task_01"

    assert events[1].event_type == "subtask_end"
    assert events[1].status_code == 0
    assert abs(events[1].latency_ms - 125.5) < 0.01


def test_wal_secret_redaction(tmp_path: Path):
    """Test redaction of GitHub PATs (ghp_*) and Bearer tokens in error messages."""
    wal_file = tmp_path / "wal_actions.log"
    wal = EventWAL(wal_file)

    secret_msg = (
        "Failed authentication using token ghp_A1b2C3d4E5f6G7h8I9j0K1L2M3N4O5P6Q7R8 "
        "and header Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"
    )
    ev = WALEvent(
        session_id="session_secret",
        step_index=1,
        event_type="error",
        error_message=secret_msg,
    )
    wal.append_event(ev)

    events = wal.read_all_events()
    assert len(events) == 1
    sanitized = events[0].error_message
    assert "ghp_" not in sanitized
    assert "eyJhbG" not in sanitized
    assert "[REDACTED_SECRET]" in sanitized

    # Direct unit test on EventWAL.redact_secrets
    assert EventWAL.redact_secrets("") == ""
    assert EventWAL.redact_secrets("Token: ghp_1234567890abcdef") == "Token: [REDACTED_SECRET]"
    assert EventWAL.redact_secrets("Auth: Bearer secret-token-1234") == "Auth: [REDACTED_SECRET]"


# =========================================================================
# 3. Atomic state snapshot write and reload for state.json
# =========================================================================


def test_atomic_state_snapshot_write_and_reload(tmp_path: Path):
    """Test saving SessionState to state.json atomically and reloading it accurately."""
    state_file = tmp_path / "state.json"
    session_state = SessionState(
        task_id="task_feature_01",
        session_id="plan_100",
        goal="Build persistence framework",
        active_step=2,
        status="running",
        memory_variables={"model": "gemini-flash", "attempt": 1},
        modified_files=["src/core.py", "tests/test_core.py"],
        dependency_graph={"task_feature_01": []},
    )

    AtomicSessionStore.save_snapshot(session_state, state_file)
    assert state_file.exists()

    # Verify atomic temp file is cleaned up
    tmp_candidate = state_file.with_suffix(".tmp")
    assert not tmp_candidate.exists()

    loaded = AtomicSessionStore.load_snapshot(state_file)
    assert loaded is not None
    assert loaded.task_id == session_state.task_id
    assert loaded.session_id == session_state.session_id
    assert loaded.goal == session_state.goal
    assert loaded.active_step == session_state.active_step
    assert loaded.status == session_state.status
    assert loaded.memory_variables == {"model": "gemini-flash", "attempt": 1}
    assert loaded.modified_files == ["src/core.py", "tests/test_core.py"]
    assert loaded.updated_at == session_state.updated_at


def test_atomic_state_snapshot_nonexistent_or_corrupt(tmp_path: Path):
    """Test load_snapshot returns None on missing and raises ValueError on corrupted file."""
    nonexistent = tmp_path / "does_not_exist.json"
    assert AtomicSessionStore.load_snapshot(nonexistent) is None

    corrupted = tmp_path / "corrupt.json"
    corrupted.write_text("{malformed json...", encoding="utf-8")
    with pytest.raises(ValueError, match="Corrupted session snapshot"):
        AtomicSessionStore.load_snapshot(corrupted)


# =========================================================================
# 4. Markdown compilation of context via compile_context_markdown and sync_context_markdown
# =========================================================================


def test_compile_context_markdown_structure():
    """Test formatting and sections of compiled context markdown."""
    state = SessionState(
        task_id="subtask_markdown",
        session_id="plan_md_01",
        goal="Verify markdown compilation output",
        active_step=3,
        status="running",
        memory_variables={"current_phase": "testing", "retry_count": 0},
        modified_files=["src/harness_agent/core/state.py"],
    )
    events = [
        WALEvent(
            session_id="plan_md_01",
            step_index=1,
            event_type="subtask_start",
            tool_name="init_subtask",
            status_code=0,
            latency_ms=10.0,
        ),
        WALEvent(
            session_id="plan_md_01",
            step_index=2,
            event_type="subtask_end",
            tool_name="init_subtask",
            status_code=1,
            latency_ms=50.2,
            error_message="Linting failure",
        ),
    ]

    md = compile_context_markdown(state, recent_events=events, max_recent_events=5)

    assert "# Active Session Context" in md
    assert "> Task ID: `subtask_markdown`" in md
    assert "Session: `plan_md_01`" in md
    assert "Status: `RUNNING`" in md
    assert "Active Step: 3" in md
    assert "## Goal\nVerify markdown compilation output" in md
    assert "## Working Memory Variables" in md
    assert "- **current_phase**: `testing`" in md
    assert "- **retry_count**: `0`" in md
    assert "## Modified Files" in md
    assert "- `src/harness_agent/core/state.py`" in md
    assert "## Recent Execution Milestones" in md
    assert "Step 1: `init_subtask` -> SUCCESS" in md
    assert "Step 2: `init_subtask` -> FAILED(1) (50.2ms) | Error: Linting failure" in md


def test_sync_context_markdown_atomicity(tmp_path: Path):
    """Test sync_context_markdown writes atomically to disk."""
    target_md = tmp_path / ".ai" / "context" / "context.md"
    state = SessionState(
        task_id="task_sync",
        session_id="sess_sync",
        goal="Atomic markdown sync",
    )

    sync_context_markdown(state, target_path=target_md)
    assert target_md.exists()
    content = target_md.read_text(encoding="utf-8")
    assert "# Active Session Context" in content
    assert "Task ID: `task_sync`" in content

    # Verify no dangling .tmp file
    assert not target_md.with_suffix(".tmp").exists()


# =========================================================================
# 5. Rehydration and state recovery via StateCoordinator and dispatch prompt injection
# =========================================================================


def test_state_coordinator_rehydration_and_recovery(tmp_path: Path):
    """Test StateCoordinator detects uncommitted WAL events and reconciles state."""
    session_file = tmp_path / "state.json"
    wal_file = tmp_path / "wal_actions.log"

    state = SessionState(
        task_id="subtask_01",
        session_id="plan_recover",
        goal="Verify state rehydration",
        active_step=1,
        status="running",
    )
    AtomicSessionStore.save_snapshot(state, session_file)

    wal = EventWAL(wal_file)
    wal.append_event(
        WALEvent(
            session_id="plan_recover",
            step_index=1,
            event_type="subtask_end",
            status_code=0,
        )
    )
    wal.append_event(
        WALEvent(
            session_id="plan_recover",
            step_index=2,
            event_type="subtask_start",
        )
    )

    coordinator = StateCoordinator(session_path=session_file, wal_path=wal_file)
    recon = coordinator.reconcile_on_startup()

    assert recon.consistent is True
    assert recon.recovered_step == 2
    assert recon.recovery_action == "advanced_to_wal"
    assert recon.reconciled_state is not None
    assert recon.reconciled_state.active_step == 2

    # Verify snapshot on disk is updated with recovered step
    reloaded = AtomicSessionStore.load_snapshot(session_file)
    assert reloaded is not None
    assert reloaded.active_step == 2


def test_herdr_dispatcher_rehydrated_context_prompt_injection(tmp_path: Path):
    """Test HerdrDispatcher injects [REHYDRATED SESSION CONTEXT] when context.md exists."""
    orig_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        context_dir = tmp_path / ".ai" / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        context_file = context_dir / "context.md"

        ctx_content = (
            "# Active Session Context\n"
            "> Task ID: `task_02` | Session: `plan_abc`\n"
            "## Goal\nRecovered Goal\n"
            "## Modified Files\n- `src/foo.py`"
        )
        context_file.write_text(ctx_content, encoding="utf-8")

        prompt = HerdrDispatcher.format_dispatch_payload(
            role="Leaf Coder Worker",
            spec_path=".ai/plans/subtasks/2026-10-27/plan_01/subtask_03.md",
            required_skills=["sdlc-clean-code-standards"],
            rehydrate_context=True,
        )

        assert "[ROLE: Leaf Coder Worker]" in prompt
        assert "[REHYDRATED SESSION CONTEXT]" in prompt
        assert "# Active Session Context" in prompt
        assert "> Task ID: `task_02` | Session: `plan_abc`" in prompt
        assert "[END REHYDRATED CONTEXT]" in prompt
    finally:
        os.chdir(orig_cwd)


def test_herdr_dispatcher_prompt_without_context_file(tmp_path: Path):
    """Test HerdrDispatcher produces standard dispatch prompt when context.md is missing."""
    orig_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        prompt = HerdrDispatcher.format_dispatch_payload(
            role="Leaf Coder Worker",
            spec_path=".ai/plans/subtasks/subtask_01.md",
            required_skills=["sdlc-clean-code-standards"],
        )

        assert "[ROLE: Leaf Coder Worker]" in prompt
        assert "[REHYDRATED SESSION CONTEXT]" not in prompt
    finally:
        os.chdir(orig_cwd)


@pytest.mark.asyncio
async def test_orchestrator_resume_plan_triggers_state_reconciliation(tmp_path: Path):
    """Test AgentOrchestrator.resume_plan reconciles state from disk."""
    orig_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        context_dir = tmp_path / ".ai" / "context"
        context_dir.mkdir(parents=True, exist_ok=True)

        session_file = context_dir / "state.json"
        wal_file = context_dir / "wal_actions.log"

        state = SessionState(
            task_id="t1",
            session_id="plan_resume",
            goal="Resume test",
            active_step=1,
            status="running",
        )
        AtomicSessionStore.save_snapshot(state, session_file)

        wal = EventWAL(wal_file)
        wal.append_event(
            WALEvent(
                session_id="plan_resume",
                step_index=1,
                event_type="subtask_end",
                status_code=0,
            )
        )
        wal.append_event(
            WALEvent(
                session_id="plan_resume",
                step_index=2,
                event_type="subtask_start",
            )
        )

        plan = OrchestrationPlan(
            plan_id="plan_resume",
            goal="Resume test",
            tasks=[
                SubTask(
                    id="t1",
                    name="Task 1",
                    role=AgentRole.CODER,
                    instruction="Do step 1",
                ),
            ],
        )

        orchestrator = AgentOrchestrator()
        # Save initial run state in state_store so resume_plan can find it
        orchestrator.state_store.save_run_state(
            plan=plan,
            task_statuses={},
            task_results={},
            status="interrupted",
        )

        with patch.object(
            orchestrator,
            "execute_subtask",
            return_value=RunResult(
                task_id="t1",
                success=True,
                exit_code=0,
                duration_seconds=0.1,
            ),
        ):
            # Pass explicit session_path and wal_path to resume_plan
            result = await orchestrator.resume_plan(
                plan_or_id="plan_resume",
                session_path=str(session_file),
                wal_path=str(wal_file),
            )

            assert result.success is True
            assert orchestrator.state_coordinator is not None
            assert orchestrator.state_coordinator.session_path == session_file
            # Snapshot was updated during run_plan execution
            reloaded = AtomicSessionStore.load_snapshot(session_file)
            assert reloaded is not None
            assert reloaded.task_id == "t1"
            assert reloaded.status == "completed"
    finally:
        os.chdir(orig_cwd)
