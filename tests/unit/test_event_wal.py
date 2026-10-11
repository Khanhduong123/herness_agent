"""Unit tests for WALEvent and EventWAL."""

import concurrent.futures
import csv
from pathlib import Path

from harness_agent.core.state import EventWAL, WALEvent


def test_wal_event_defaults():
    event = WALEvent(session_id="sess-1", step_index=1, event_type="action_start")
    assert event.session_id == "sess-1"
    assert event.step_index == 1
    assert event.event_type == "action_start"
    assert event.tool_name == ""
    assert event.status_code == 0
    assert event.latency_ms == 0.0
    assert event.error_message == ""
    assert event.timestamp > 0


def test_tc01_append_single_event(tmp_path: Path):
    wal_file = tmp_path / "test_wal.csv"
    wal = EventWAL(wal_file)

    event = WALEvent(
        session_id="sess-1",
        step_index=0,
        event_type="checkpoint",
        tool_name="save_state",
        status_code=200,
        latency_ms=12.5,
        error_message="",
    )
    wal.append_event(event)

    events = wal.read_all_events()
    assert len(events) == 1
    loaded = events[0]
    assert loaded.session_id == "sess-1"
    assert loaded.step_index == 0
    assert loaded.event_type == "checkpoint"
    assert loaded.tool_name == "save_state"
    assert loaded.status_code == 200
    assert loaded.latency_ms == 12.5
    assert loaded.error_message == ""

    # Check raw CSV header
    with open(wal_file, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == EventWAL.CSV_HEADER


def test_tc02_read_last_event(tmp_path: Path):
    wal_file = tmp_path / "test_wal_sequence.csv"
    wal = EventWAL(wal_file)

    for i in range(5):
        event = WALEvent(
            session_id="sess-seq",
            step_index=i,
            event_type="tool_call",
            tool_name=f"tool_{i}",
        )
        wal.append_event(event)

    last_event = wal.read_last_event()
    assert last_event is not None
    assert last_event.step_index == 4
    assert last_event.tool_name == "tool_4"
    assert len(wal.read_all_events()) == 5


def test_tc03_comma_and_newline_quoting(tmp_path: Path):
    wal_file = tmp_path / "test_wal_quotes.csv"
    wal = EventWAL(wal_file)

    tricky_error = 'Error occurred: "Fatal issue", line 42\nTraceback:\nValueError: invalid input'
    event = WALEvent(
        session_id="sess-quotes",
        step_index=1,
        event_type="error",
        error_message=tricky_error,
    )
    wal.append_event(event)

    events = wal.read_all_events()
    assert len(events) == 1
    assert events[0].error_message == tricky_error
    last_event = wal.read_last_event()
    assert last_event is not None
    assert last_event.error_message == tricky_error


def test_tc04_secret_redaction(tmp_path: Path):
    wal_file = tmp_path / "test_wal_secrets.csv"
    wal = EventWAL(wal_file)

    raw_error = "Request failed with ghp_1234567890abcdef and Bearer my-secret-token-123456"
    event = WALEvent(
        session_id="sess-sec",
        step_index=2,
        event_type="error",
        error_message=raw_error,
    )
    wal.append_event(event)

    events = wal.read_all_events()
    assert len(events) == 1
    redacted = events[0].error_message
    assert "ghp_1234567890abcdef" not in redacted
    assert "Bearer my-secret-token-123456" not in redacted
    assert "[REDACTED_SECRET]" in redacted


def test_edge_case_empty_or_missing_wal_file(tmp_path: Path):
    missing_file = tmp_path / "non_existent.csv"
    wal = EventWAL.__new__(EventWAL)
    wal.wal_path = missing_file
    import threading

    wal._lock = threading.Lock()

    assert wal.read_all_events() == []
    assert wal.read_last_event() is None

    # Empty file with 0 bytes
    empty_file = tmp_path / "empty.csv"
    empty_file.touch()
    wal2 = EventWAL.__new__(EventWAL)
    wal2.wal_path = empty_file
    wal2._lock = threading.Lock()
    assert wal2.read_all_events() == []
    assert wal2.read_last_event() is None


def test_concurrent_multithreaded_appends(tmp_path: Path):
    wal_file = tmp_path / "test_wal_concurrent.csv"
    wal = EventWAL(wal_file)

    num_threads = 10
    events_per_thread = 20

    def append_batch(thread_id: int):
        for i in range(events_per_thread):
            event = WALEvent(
                session_id=f"thread-{thread_id}",
                step_index=i,
                event_type="action_end",
                latency_ms=1.0 * i,
                error_message=f"Thread {thread_id} log, line {i}",
            )
            wal.append_event(event)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(append_batch, tid) for tid in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    all_events = wal.read_all_events()
    assert len(all_events) == num_threads * events_per_thread
