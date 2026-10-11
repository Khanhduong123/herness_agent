"""DAG state persistence and SQLite storage for resume capability."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlmodel import Field, Session, SQLModel, create_engine, select

from harness_agent.core.models import OrchestrationPlan, RunResult, TaskStatus


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
