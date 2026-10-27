"""DAG state persistence and SQLite storage for resume capability."""

from __future__ import annotations

import csv
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel
from pydantic import Field as PydanticField
from sqlalchemy import text
from sqlmodel import Field, Session, SQLModel, create_engine, select

from harness_agent.core.models import OrchestrationPlan, RunResult, TaskStatus

DEFAULT_CONTEXT_DIR = ".ai/context"
DEFAULT_STATE_SNAPSHOT_FILE = ".ai/context/state.json"
DEFAULT_WAL_ACTIONS_FILE = ".ai/context/wal_actions.log"
DEFAULT_CONTEXT_MD_FILE = ".ai/context/context.md"


def check_token_compaction_trigger(
    current_tokens: int,
    max_tokens: int,
    threshold_ratio: float = 0.65,
) -> bool:
    """Determines if conversational history requires compaction based on token usage.

    Args:
        current_tokens (int): Current count of tokens in active context.
        max_tokens (int): Maximum token capacity of the model context window.
        threshold_ratio (float): Ratio triggering compaction (default 0.65).

    Returns:
        bool: True if compaction should be triggered, False otherwise.
    """
    if not (0.1 <= threshold_ratio <= 1.0):
        raise ValueError(f"threshold_ratio must be between 0.1 and 1.0, got {threshold_ratio}")
    if max_tokens <= 0 or current_tokens <= 0:
        return False
    return (current_tokens / max_tokens) >= threshold_ratio


def compact_history_to_checkpoint(
    turns: List[Dict[str, Any]],
    preserve_recent: int = 3,
) -> List[Dict[str, Any]]:
    """Condenses older turns into a structured checkpoint summary while
    maintaining exact recent records.

    Args:
        turns: Complete history turns list.
        preserve_recent: Number of most recent turns to keep intact.

    Returns:
        List of compacted turns with a checkpoint summary turn at the
        beginning if older turns exist.
    """
    if not turns:
        return []

    if preserve_recent < 0:
        preserve_recent = 0

    if len(turns) <= preserve_recent:
        return [dict(t) for t in turns]

    summary_text, recent_turns = compress_history(turns, window_size=preserve_recent)
    checkpoint_turn: Dict[str, Any] = {
        "role": "system",
        "checkpoint": True,
        "content": summary_text,
        "summarized_turns_count": len(turns) - len(recent_turns),
    }
    return [checkpoint_turn] + [dict(t) for t in recent_turns]


def compress_history(
    events: List[Dict[str, Any]],
    window_size: int = 5,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Compresses event history into a micro-summary and a trailing active window.

    Args:
        events: Full list of interaction events or tool calls.
        window_size: Number of recent turns to retain verbatim.

    Returns:
        Tuple of (summary_markdown, recent_active_events).
    """
    if not events:
        return "", []

    if len(events) <= window_size:
        return "", list(events)

    cutoff = len(events) - window_size
    older_events = events[:cutoff]
    recent_events = events[cutoff:]

    summary_lines = ["### Execution History Summary", ""]

    # Track repeated tool executions to collapse duplicates
    # Structure of summarized entries: (action_summary, status_summary, key_facts)
    summarized_items: List[Dict[str, Any]] = []

    for event in older_events:
        if not isinstance(event, dict):
            summarized_items.append(
                {
                    "action": "non-dict event",
                    "status": "unknown",
                    "facts": str(event),
                    "count": 1,
                }
            )
            continue

        tool_calls = event.get("tool_calls") or []
        action_parts: List[str] = []
        if isinstance(tool_calls, list) and tool_calls:
            for tc in tool_calls:
                if isinstance(tc, dict):
                    name = tc.get("name") or tc.get("tool") or "unknown_tool"
                    args = tc.get("args") or tc.get("arguments") or {}
                    target_file = ""
                    if isinstance(args, dict):
                        target_file = (
                            args.get("TargetFile")
                            or args.get("file_path")
                            or args.get("path")
                            or ""
                        )
                    if target_file:
                        action_parts.append(f"{name}({target_file})")
                    else:
                        action_parts.append(f"{name}")
                else:
                    action_parts.append(str(tc))
        elif event.get("tool"):
            tool_name = event.get("tool")
            target_file = event.get("file") or event.get("path") or ""
            if target_file:
                action_parts.append(f"{tool_name}({target_file})")
            else:
                action_parts.append(f"{tool_name}")
        elif event.get("action"):
            action_parts.append(str(event.get("action")))
        elif event.get("role"):
            action_parts.append(f"{event.get('role')} message")
        else:
            action_parts.append("interaction turn")

        action_str = ", ".join(action_parts) if action_parts else "interaction turn"

        status_str = "success"
        if event.get("status"):
            status_str = str(event.get("status"))
        elif event.get("error") or event.get("is_error"):
            status_str = f"failure ({event.get('error') or 'error'})"
        elif event.get("returncode") is not None:
            rc = event.get("returncode")
            status_str = "success" if rc == 0 else f"failure (code {rc})"
        elif event.get("exit_code") is not None:
            ec = event.get("exit_code")
            status_str = "success" if ec == 0 else f"failure (code {ec})"

        facts_str = ""
        if event.get("facts"):
            facts_str = str(event.get("facts"))
        elif event.get("summary"):
            facts_str = str(event.get("summary"))
        elif event.get("decision"):
            facts_str = str(event.get("decision"))
        elif event.get("output"):
            out = str(event.get("output")).strip()
            if len(out) > 80:
                out = out[:77] + "..."
            facts_str = out
        elif event.get("content"):
            cnt = str(event.get("content")).strip()
            if len(cnt) > 80:
                cnt = cnt[:77] + "..."
            facts_str = cnt

        # Check for repeated identical turn/failure to collapse
        if (
            summarized_items
            and summarized_items[-1]["action"] == action_str
            and summarized_items[-1]["status"] == status_str
            and summarized_items[-1]["facts"] == facts_str
        ):
            summarized_items[-1]["count"] += 1
        else:
            summarized_items.append(
                {
                    "action": action_str,
                    "status": status_str,
                    "facts": facts_str,
                    "count": 1,
                }
            )

    for idx, item in enumerate(summarized_items, 1):
        count_suffix = f" (repeated {item['count']}x)" if item["count"] > 1 else ""
        line = f"- Step {idx}: Action: `{item['action']}` | Status: `{item['status']}`"
        if item["facts"]:
            line += f" | Key facts: {item['facts']}"
        line += count_suffix
        summary_lines.append(line)

    return "\n".join(summary_lines), list(recent_events)


class OrchestrationRunRecord(SQLModel, table=True):
    """Database model for storing orchestration run records."""

    __tablename__ = "orchestration_runs"

    plan_id: str = Field(primary_key=True)
    goal: str
    status: str
    plan_file: Optional[str] = None
    plan_data: str
    task_statuses: str
    task_results: str
    created_at: float
    updated_at: float


class DAGStateStore:
    """Manages persistent SQLite storage and Markdown synchronization

    for Orchestration Task DAG states, enabling resume capabilities.
    """

    DEFAULT_DB_PATH = ".runs/orchestrator_state.db"

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = str(db_path or self.DEFAULT_DB_PATH)
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        # Use sqlite URL format for SQLAlchemy/SQLModel
        normalized_path = Path(self.db_path).resolve().as_posix()
        self.engine = create_engine(f"sqlite:///{normalized_path}", echo=False)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize SQLite schema if not exists and configure PRAGMA."""
        with self.engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.commit()
        SQLModel.metadata.create_all(self.engine)

    def save_run_state(
        self,
        plan: OrchestrationPlan,
        task_statuses: Dict[str, TaskStatus],
        task_results: Dict[str, RunResult],
        status: str = "running",
        plan_file: Optional[str] = None,
    ) -> None:
        """Persist or update complete orchestration plan and DAG status in SQLite."""
        now = time.time()
        plan_json = json.dumps(plan.model_dump())
        statuses_json = json.dumps({k: v.value for k, v in task_statuses.items()})
        results_json = json.dumps({k: v.model_dump() for k, v in task_results.items()})

        effective_plan_file = plan_file
        with Session(self.engine) as session:
            record = session.get(OrchestrationRunRecord, plan.plan_id)
            if record:
                record.goal = plan.goal
                record.status = status
                if plan_file:
                    record.plan_file = plan_file
                effective_plan_file = record.plan_file
                record.plan_data = plan_json
                record.task_statuses = statuses_json
                record.task_results = results_json
                record.updated_at = now
            else:
                record = OrchestrationRunRecord(
                    plan_id=plan.plan_id,
                    goal=plan.goal,
                    status=status,
                    plan_file=plan_file,
                    plan_data=plan_json,
                    task_statuses=statuses_json,
                    task_results=results_json,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
            session.commit()

        if effective_plan_file and effective_plan_file.endswith(".md"):
            self.update_markdown_status(effective_plan_file, task_statuses, plan.goal)

    def update_task_status(
        self,
        plan_id: str,
        task_id: str,
        status: TaskStatus,
        result: Optional[RunResult] = None,
        overall_status: Optional[str] = None,
        plan_file: Optional[str] = None,
    ) -> None:
        """Continuously update status of a single task in SQLite and optional Markdown."""
        now = time.time()
        with Session(self.engine) as session:
            record = session.get(OrchestrationRunRecord, plan_id)
            if not record:
                return

            statuses: Dict[str, str] = json.loads(record.task_statuses)
            results: Dict[str, Any] = json.loads(record.task_results)
            effective_plan_file = plan_file or record.plan_file
            goal = record.goal
            current_overall = overall_status or record.status

            statuses[task_id] = status.value
            if result:
                results[task_id] = result.model_dump()

            record.task_statuses = json.dumps(statuses)
            record.task_results = json.dumps(results)
            record.updated_at = now
            record.status = current_overall
            session.commit()

        typed_statuses = {k: TaskStatus(v) for k, v in statuses.items()}
        if effective_plan_file and effective_plan_file.endswith(".md"):
            self.update_markdown_status(effective_plan_file, typed_statuses, goal)

    def load_run_state(self, plan_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Load state for a specific plan_id or the most recently updated run."""
        with Session(self.engine) as session:
            if plan_id:
                record = session.get(OrchestrationRunRecord, plan_id)
            else:
                stmt = (
                    select(OrchestrationRunRecord)
                    .order_by(OrchestrationRunRecord.updated_at.desc())
                    .limit(1)
                )
                record = session.exec(stmt).first()

            if not record:
                return None

            raw_statuses = json.loads(record.task_statuses)
            raw_results = json.loads(record.task_results)
            plan_dict = json.loads(record.plan_data)

            return {
                "plan_id": record.plan_id,
                "goal": record.goal,
                "status": record.status,
                "plan_file": record.plan_file,
                "plan": OrchestrationPlan(**plan_dict),
                "task_statuses": {k: TaskStatus(v) for k, v in raw_statuses.items()},
                "task_results": {k: RunResult(**v) for k, v in raw_results.items()},
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }

    def list_runs(self) -> List[Dict[str, Any]]:
        """List all tracked orchestration runs."""
        with Session(self.engine) as session:
            stmt = select(OrchestrationRunRecord).order_by(OrchestrationRunRecord.updated_at.desc())
            records = session.exec(stmt).all()
            return [
                {
                    "plan_id": r.plan_id,
                    "goal": r.goal,
                    "status": r.status,
                    "plan_file": r.plan_file,
                    "created_at": r.created_at,
                    "updated_at": r.updated_at,
                }
                for r in records
            ]

    @staticmethod
    def update_markdown_status(
        file_path: str,
        task_statuses: Dict[str, TaskStatus],
        goal: Optional[str] = None,
    ) -> None:
        """Update or insert status block and frontmatter in a markdown plan file."""
        path = Path(file_path)
        if not path.exists():
            return

        content = path.read_text(encoding="utf-8")
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

        # Build Markdown status table block
        table_lines = [
            "<!-- DAG_STATUS_START -->",
            "## Task DAG Execution Status",
            f"> Last Updated: `{timestamp}`",
            "",
            "| Task ID | Status | State Icon |",
            "| :--- | :--- | :--- |",
        ]
        status_icons = {
            TaskStatus.PENDING: "[PENDING]",
            TaskStatus.RUNNING: "[RUNNING]",
            TaskStatus.VALIDATING: "[VALIDATING]",
            TaskStatus.COMPLETED: "[COMPLETED]",
            TaskStatus.FAILED: "[FAILED]",
            TaskStatus.BLOCKED: "[BLOCKED]",
            TaskStatus.SKIPPED: "[SKIPPED]",
        }
        for tid, st in task_statuses.items():
            icon = status_icons.get(st, st.value.upper())
            table_lines.append(f"| `{tid}` | {st.value.upper()} | {icon} |")
        table_lines.append("<!-- DAG_STATUS_END -->")
        new_block = "\n".join(table_lines)

        # Replace existing block if present
        pattern = r"<!-- DAG_STATUS_START -->.*?<!-- DAG_STATUS_END -->"
        if re.search(pattern, content, flags=re.DOTALL):
            updated_content = re.sub(pattern, new_block, content, flags=re.DOTALL)
        else:
            updated_content = content.rstrip() + "\n\n" + new_block + "\n"

        path.write_text(updated_content, encoding="utf-8")


def compile_context_markdown(
    state: SessionState,
    recent_events: Optional[List[WALEvent]] = None,
    max_recent_events: int = 5,
) -> str:
    """Compiles machine state and recent WAL events into a concise markdown context summary.

    Designed for direct injection into the Agent System Prompt during session rehydration.
    Omits historical chat bloat and provides high-signal working memory.
    """
    updated_iso = datetime.fromtimestamp(state.updated_at, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%SZ"
    )
    header_meta = (
        f"> Task ID: `{state.task_id}` | Session: `{state.session_id}` "
        f"| Status: `{state.status.upper()}`"
    )
    lines = [
        "# Active Session Context",
        header_meta,
        f"> Active Step: {state.active_step} | Updated: {updated_iso}",
        "",
        f"## Goal\n{state.goal.strip()}",
        "",
    ]

    if state.memory_variables:
        lines.append("## Working Memory Variables")
        for k, v in state.memory_variables.items():
            lines.append(f"- **{k}**: `{v}`")
        lines.append("")

    if state.modified_files:
        lines.append("## Modified Files")
        for f in state.modified_files:
            lines.append(f"- `{f}`")
        lines.append("")

    if recent_events:
        lines.append("## Recent Execution Milestones")
        events_slice = recent_events[-max_recent_events:]
        for ev in events_slice:
            status_text = "SUCCESS" if ev.status_code == 0 else f"FAILED({ev.status_code})"
            action = f"`{ev.tool_name}`" if ev.tool_name else f"`{ev.event_type}`"
            err = f" | Error: {ev.error_message}" if ev.error_message else ""
            lines.append(
                f"- Step {ev.step_index}: {action} -> {status_text} ({ev.latency_ms:.1f}ms){err}"
            )
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def sync_context_markdown(
    state: SessionState,
    target_path: Union[str, Path] = DEFAULT_CONTEXT_MD_FILE,
    recent_events: Optional[List[WALEvent]] = None,
) -> None:
    """Compiles state and writes context.md atomically."""
    md_content = compile_context_markdown(state, recent_events)
    path = Path(target_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(md_content, encoding="utf-8")
    os.replace(tmp_path, path)


class SessionState(BaseModel):
    """Working memory and state snapshot for a subtask execution session."""

    task_id: str
    session_id: str
    goal: str
    active_step: int = 0
    memory_variables: Dict[str, Any] = PydanticField(default_factory=dict)
    modified_files: List[str] = PydanticField(default_factory=list)
    dependency_graph: Dict[str, List[str]] = PydanticField(default_factory=dict)
    status: str = "active"
    updated_at: float = PydanticField(default_factory=time.time)


class AtomicSessionStore:
    """Provides atomic write-then-rename persistence and loading for SessionState."""

    @staticmethod
    def save_snapshot(state: SessionState, target_path: Union[str, Path]) -> None:
        """Atomically writes session state using write-then-rename semantics.

        Ensures parent directories exist, writes serialized JSON to a temporary file,
        and atomically replaces the target path with retry on transient PermissionErrors.
        """
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target.with_suffix(f"{target.suffix}.tmp" if target.suffix else ".tmp")

        payload = state.model_dump_json(indent=2)
        tmp_path.write_text(payload, encoding="utf-8")

        max_retries = 3
        backoff_sec = 0.05
        for attempt in range(max_retries):
            try:
                os.replace(tmp_path, target)
                break
            except PermissionError:
                if attempt == max_retries - 1:
                    raise
                time.sleep(backoff_sec)

    @staticmethod
    def load_snapshot(target_path: Union[str, Path]) -> Optional[SessionState]:
        """Loads session snapshot from target path, returning None if missing.

        Raises:
            ValueError: If the file contents are malformed JSON or invalid schema.
        """
        target = Path(target_path)
        if not target.exists():
            return None

        try:
            content = target.read_text(encoding="utf-8")
            data = json.loads(content)
            return SessionState.model_validate(data)
        except (json.JSONDecodeError, Exception) as exc:
            raise ValueError(f"Corrupted session snapshot at {target_path}") from exc


class WALEvent(BaseModel):
    """Event entry in the Write-Ahead Log."""

    timestamp: float = PydanticField(default_factory=time.time)
    session_id: str
    step_index: int
    event_type: str
    tool_name: str = ""
    status_code: int = 0
    latency_ms: float = 0.0
    error_message: str = ""


class EventWAL:
    """Append-only Write-Ahead Log (WAL) logger using CSV storage with secret redaction
    and thread safety.
    """

    CSV_HEADER: List[str] = [
        "timestamp",
        "session_id",
        "step_index",
        "event_type",
        "tool_name",
        "status_code",
        "latency_ms",
        "error_message",
    ]

    _SECRET_PATTERNS = [
        re.compile(r"ghp_[a-zA-Z0-9_-]+"),
        re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]+"),
    ]

    def __init__(self, wal_path: Union[str, Path]) -> None:
        self.wal_path = Path(wal_path)
        self.wal_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

        # Initialize CSV with header if file is missing or 0 bytes
        with self._lock:
            if not self.wal_path.exists() or self.wal_path.stat().st_size == 0:
                with open(self.wal_path, mode="w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
                    writer.writerow(self.CSV_HEADER)

    @classmethod
    def redact_secrets(cls, message: str) -> str:
        """Redacts sensitive tokens in error messages."""
        if not message:
            return ""
        sanitized = message
        for pattern in cls._SECRET_PATTERNS:
            sanitized = pattern.sub("[REDACTED_SECRET]", sanitized)
        return sanitized

    def append_event(self, event: WALEvent) -> None:
        """Synchronously appends a WALEvent to the log CSV and flushes."""
        redacted_error = self.redact_secrets(event.error_message)
        row = [
            str(event.timestamp),
            str(event.session_id),
            str(event.step_index),
            str(event.event_type),
            str(event.tool_name),
            str(event.status_code),
            str(event.latency_ms),
            redacted_error,
        ]
        with self._lock:
            with open(self.wal_path, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
                writer.writerow(row)
                f.flush()

    def read_all_events(self) -> List[WALEvent]:
        """Parses and returns all WAL events in order."""
        with self._lock:
            if not self.wal_path.exists():
                return []

            events: List[WALEvent] = []
            with open(self.wal_path, mode="r", newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header:
                    return []

                for row in reader:
                    if not row:
                        continue
                    # Pad missing columns if any
                    while len(row) < len(self.CSV_HEADER):
                        row.append("")
                    event = WALEvent(
                        timestamp=float(row[0]) if row[0] else time.time(),
                        session_id=row[1],
                        step_index=int(row[2]) if row[2] else 0,
                        event_type=row[3],
                        tool_name=row[4],
                        status_code=int(row[5]) if row[5] else 0,
                        latency_ms=float(row[6]) if row[6] else 0.0,
                        error_message=row[7],
                    )
                    events.append(event)
            return events

    def read_last_event(self) -> Optional[WALEvent]:
        """Returns the most recent WAL event or None."""
        events = self.read_all_events()
        if not events:
            return None
        return events[-1]


class ReconciliationResult(BaseModel):
    """Result of state reconciliation between session snapshot and WAL."""

    consistent: bool
    recovered_step: int
    reconciled_state: Optional[SessionState] = None
    uncommitted_events: List[WALEvent] = PydanticField(default_factory=list)
    recovery_action: str = "none"


class StateCoordinator:
    """Coordinates crash recovery and consistency validation between
    session snapshot and event WAL.
    """

    def __init__(
        self,
        session_path: Optional[Union[str, Path]] = None,
        wal_path: Optional[Union[str, Path]] = None,
        context_dir: Optional[Union[str, Path]] = None,
    ) -> None:
        base_dir = Path(context_dir or DEFAULT_CONTEXT_DIR)
        self.session_path = Path(session_path or base_dir / "state.json")
        self.wal_path = Path(wal_path or base_dir / "wal_actions.log")
        self.context_md_path = base_dir / "context.md"
        self.wal = EventWAL(self.wal_path)

    def reconcile_on_startup(self) -> ReconciliationResult:
        """Validates consistency between session.json and log.csv on agent boot.

        Handles:
        - Fresh Run: neither snapshot nor WAL events exist.
        - Normal/Clean: snapshot active_step matches last WAL event step_index.
        - WAL Ahead: WAL recorded step K while snapshot is at K-1 (advances snapshot).
        - Snapshot Missing: WAL exists; reconstructs SessionState from WAL events.
        - Snapshot Ahead: snapshot step > last WAL step; trusts snapshot with warning.
        - Interrupted Action: last WAL event is an uncompleted action/tool call.
        - Trailing Error: last WAL event has status_code != 0.
        """
        snapshot = AtomicSessionStore.load_snapshot(self.session_path)
        all_events = self.wal.read_all_events()
        last_event = all_events[-1] if all_events else None

        # Edge Case 1: Fresh run (neither snapshot nor WAL events exist)
        if snapshot is None and not all_events:
            return ReconciliationResult(
                consistent=True,
                recovered_step=0,
                reconciled_state=None,
                uncommitted_events=[],
                recovery_action="fresh_init",
            )

        # Edge Case 3: Trailing Error in WAL (status_code != 0)
        if last_event is not None and last_event.status_code != 0:
            active_step = last_event.step_index
            if snapshot is not None:
                snapshot.active_step = active_step
                snapshot.status = "error"
                AtomicSessionStore.save_snapshot(snapshot, self.session_path)
            return ReconciliationResult(
                consistent=False,
                recovered_step=active_step,
                reconciled_state=snapshot,
                uncommitted_events=[last_event],
                recovery_action="error_detected",
            )

        # Scenario D: Interrupted Action
        # Last WAL event is action_start or tool_call without closing status
        if last_event is not None and last_event.event_type in (
            "action_start",
            "tool_call",
            "action_in_progress",
        ):
            active_step = last_event.step_index
            return ReconciliationResult(
                consistent=False,
                recovered_step=active_step,
                reconciled_state=snapshot,
                uncommitted_events=[last_event],
                recovery_action="interrupted_action_detected",
            )

        # Scenario C & Edge Case 2: Snapshot Missing, WAL exists
        if snapshot is None and all_events:
            last_ev = all_events[-1]
            reconstructed_state = SessionState(
                task_id=f"recovered_{last_ev.session_id}",
                session_id=last_ev.session_id,
                goal=f"Reconstructed from WAL for session {last_ev.session_id}",
                active_step=last_ev.step_index,
                status="recovered",
            )
            AtomicSessionStore.save_snapshot(reconstructed_state, self.session_path)
            return ReconciliationResult(
                consistent=True,
                recovered_step=last_ev.step_index,
                reconciled_state=reconstructed_state,
                uncommitted_events=[],
                recovery_action="replayed_from_log",
            )

        # At this point, snapshot is not None
        assert snapshot is not None

        # Snapshot exists, but no WAL events exist
        if not all_events:
            return ReconciliationResult(
                consistent=True,
                recovered_step=snapshot.active_step,
                reconciled_state=snapshot,
                uncommitted_events=[],
                recovery_action="none",
            )

        last_ev = all_events[-1]

        # Scenario A: Normal/Clean (snapshot step == last event step)
        if snapshot.active_step == last_ev.step_index:
            return ReconciliationResult(
                consistent=True,
                recovered_step=snapshot.active_step,
                reconciled_state=snapshot,
                uncommitted_events=[],
                recovery_action="none",
            )

        # Scenario B: WAL Ahead of Snapshot
        if last_ev.step_index > snapshot.active_step:
            uncommitted = [e for e in all_events if e.step_index > snapshot.active_step]
            snapshot.active_step = last_ev.step_index
            AtomicSessionStore.save_snapshot(snapshot, self.session_path)
            return ReconciliationResult(
                consistent=True,
                recovered_step=last_ev.step_index,
                reconciled_state=snapshot,
                uncommitted_events=uncommitted,
                recovery_action="advanced_to_wal",
            )

        # Edge Case 4: Snapshot Ahead of WAL (snapshot step > last WAL step)
        # Trust snapshot but record warning action
        return ReconciliationResult(
            consistent=True,
            recovered_step=snapshot.active_step,
            reconciled_state=snapshot,
            uncommitted_events=[],
            recovery_action="snapshot_ahead_of_wal",
        )
