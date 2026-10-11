"""Unit tests for SessionState and AtomicSessionStore working memory snapshotting."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from harness_agent.core.state import AtomicSessionStore, SessionState


def test_session_state_defaults():
    state = SessionState(
        task_id="task_01",
        session_id="sess_abc",
        goal="Implement snapshotting",
    )
    assert state.task_id == "task_01"
    assert state.session_id == "sess_abc"
    assert state.goal == "Implement snapshotting"
    assert state.active_step == 0
    assert state.memory_variables == {}
    assert state.modified_files == []
    assert state.dependency_graph == {}
    assert state.status == "active"
    assert isinstance(state.updated_at, float)


def test_session_state_save_and_load(tmp_path: Path):
    target = tmp_path / "session_state.json"
    state = SessionState(
        task_id="subtask_01",
        session_id="sess_123",
        goal="Test saving snapshot",
        active_step=4,
        memory_variables={"var1": "value1", "count": 10},
        modified_files=["src/module.py", "tests/test_module.py"],
        dependency_graph={"step_2": ["step_1"]},
        status="in_progress",
    )

    AtomicSessionStore.save_snapshot(state, target)
    assert target.exists()

    loaded = AtomicSessionStore.load_snapshot(target)
    assert loaded is not None
    assert loaded.task_id == state.task_id
    assert loaded.session_id == state.session_id
    assert loaded.goal == state.goal
    assert loaded.active_step == 4
    assert loaded.memory_variables == {"var1": "value1", "count": 10}
    assert loaded.modified_files == ["src/module.py", "tests/test_module.py"]
    assert loaded.dependency_graph == {"step_2": ["step_1"]}
    assert loaded.status == "in_progress"
    assert loaded.updated_at == state.updated_at


def test_atomic_overwrite_consecutive_saves(tmp_path: Path):
    target = tmp_path / "state_overwrite.json"
    state1 = SessionState(
        task_id="t1",
        session_id="s1",
        goal="Step 1",
        active_step=1,
    )
    AtomicSessionStore.save_snapshot(state1, target)

    state2 = SessionState(
        task_id="t1",
        session_id="s1",
        goal="Step 2",
        active_step=2,
    )
    AtomicSessionStore.save_snapshot(state2, target)

    loaded = AtomicSessionStore.load_snapshot(target)
    assert loaded is not None
    assert loaded.active_step == 2
    assert loaded.goal == "Step 2"


def test_load_missing_file_returns_none(tmp_path: Path):
    missing_path = tmp_path / "non_existent_snapshot.json"
    result = AtomicSessionStore.load_snapshot(missing_path)
    assert result is None


def test_load_corrupted_json_raises_value_error(tmp_path: Path):
    corrupted_path = tmp_path / "corrupted.json"
    corrupted_path.write_text("invalid json contents", encoding="utf-8")

    with pytest.raises(ValueError, match="Corrupted session snapshot"):
        AtomicSessionStore.load_snapshot(corrupted_path)


def test_load_invalid_schema_raises_value_error(tmp_path: Path):
    invalid_schema_path = tmp_path / "invalid_schema.json"
    invalid_schema_path.write_text('{"unknown_field": 123}', encoding="utf-8")

    with pytest.raises(ValueError, match="Corrupted session snapshot"):
        AtomicSessionStore.load_snapshot(invalid_schema_path)


def test_save_snapshot_creates_nested_parent_dirs(tmp_path: Path):
    nested_path = tmp_path / "deep" / "nested" / "dir" / "snapshot.json"
    state = SessionState(
        task_id="t_nested",
        session_id="s_nested",
        goal="Nested dirs test",
    )
    AtomicSessionStore.save_snapshot(state, nested_path)
    assert nested_path.exists()
    loaded = AtomicSessionStore.load_snapshot(nested_path)
    assert loaded is not None
    assert loaded.task_id == "t_nested"


def test_save_snapshot_permission_error_retry(tmp_path: Path):
    target = tmp_path / "snapshot_retry.json"
    state = SessionState(
        task_id="t_retry",
        session_id="s_retry",
        goal="Test retry",
    )

    original_replace = os.replace
    calls = []

    def mock_replace(src, dst):
        calls.append((src, dst))
        if len(calls) == 1:
            raise PermissionError("Access is denied")
        return original_replace(src, dst)

    with patch("os.replace", side_effect=mock_replace):
        AtomicSessionStore.save_snapshot(state, target)

    assert len(calls) == 2
    assert target.exists()
    loaded = AtomicSessionStore.load_snapshot(target)
    assert loaded is not None
    assert loaded.task_id == "t_retry"


def test_save_snapshot_permission_error_exceeds_retries(tmp_path: Path):
    target = tmp_path / "snapshot_fail.json"
    state = SessionState(
        task_id="t_fail",
        session_id="s_fail",
        goal="Test fail retry",
    )

    with patch("os.replace", side_effect=PermissionError("Locked permanently")):
        with pytest.raises(PermissionError):
            AtomicSessionStore.save_snapshot(state, target)
