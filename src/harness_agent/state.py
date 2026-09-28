"""DAG state persistence and SQLite storage for resume capability."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from harness_agent.models import OrchestrationPlan, RunResult, TaskStatus


class DAGStateStore:
    """Manages persistent SQLite storage and Markdown synchronization

    for Orchestration Task DAG states, enabling resume capabilities.
    """

    DEFAULT_DB_PATH = ".runs/orchestrator_state.db"

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = str(db_path or self.DEFAULT_DB_PATH)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a sqlite connection with row access by column name."""
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        """Initialize SQLite schema if not exists."""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orchestration_runs (
                    plan_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plan_file TEXT,
                    plan_data TEXT NOT NULL,
                    task_statuses TEXT NOT NULL,
                    task_results TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.commit()

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

        with self._get_connection() as conn:
            # Check if record exists to keep original created_at
            cur = conn.cursor()
            cur.execute(
                "SELECT created_at, plan_file FROM orchestration_runs WHERE plan_id = ?",
                (plan.plan_id,),
            )
            row = cur.fetchone()
            if row:
                created_at = row["created_at"]
                effective_plan_file = plan_file or row["plan_file"]
            else:
                created_at = now
                effective_plan_file = plan_file

            conn.execute(
                """
                INSERT INTO orchestration_runs (
                    plan_id, goal, status, plan_file, plan_data,
                    task_statuses, task_results, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(plan_id) DO UPDATE SET
                    goal=excluded.goal,
                    status=excluded.status,
                    plan_file=coalesce(excluded.plan_file, orchestration_runs.plan_file),
                    plan_data=excluded.plan_data,
                    task_statuses=excluded.task_statuses,
                    task_results=excluded.task_results,
                    updated_at=excluded.updated_at
                """,
                (
                    plan.plan_id,
                    plan.goal,
                    status,
                    effective_plan_file,
                    plan_json,
                    statuses_json,
                    results_json,
                    created_at,
                    now,
                ),
            )
            conn.commit()

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
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT goal, task_statuses, task_results, plan_file, status
                FROM orchestration_runs WHERE plan_id = ?
                """,
                (plan_id,),
            )
            row = cur.fetchone()
            if not row:
                return

            statuses: Dict[str, str] = json.loads(row["task_statuses"])
            results: Dict[str, Any] = json.loads(row["task_results"])
            effective_plan_file = plan_file or row["plan_file"]
            goal = row["goal"]
            current_overall = overall_status or row["status"]

            statuses[task_id] = status.value
            if result:
                results[task_id] = result.model_dump()

            conn.execute(
                """
                UPDATE orchestration_runs
                SET task_statuses = ?, task_results = ?, updated_at = ?, status = ?
                WHERE plan_id = ?
                """,
                (
                    json.dumps(statuses),
                    json.dumps(results),
                    now,
                    current_overall,
                    plan_id,
                ),
            )
            conn.commit()

        typed_statuses = {k: TaskStatus(v) for k, v in statuses.items()}
        if effective_plan_file and effective_plan_file.endswith(".md"):
            self.update_markdown_status(effective_plan_file, typed_statuses, goal)

    def load_run_state(self, plan_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Load state for a specific plan_id or the most recently updated run."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            if plan_id:
                cur.execute(
                    "SELECT * FROM orchestration_runs WHERE plan_id = ?",
                    (plan_id,),
                )
            else:
                cur.execute("SELECT * FROM orchestration_runs ORDER BY updated_at DESC LIMIT 1")

            row = cur.fetchone()
            if not row:
                return None

            raw_statuses = json.loads(row["task_statuses"])
            raw_results = json.loads(row["task_results"])
            plan_dict = json.loads(row["plan_data"])

            return {
                "plan_id": row["plan_id"],
                "goal": row["goal"],
                "status": row["status"],
                "plan_file": row["plan_file"],
                "plan": OrchestrationPlan(**plan_dict),
                "task_statuses": {k: TaskStatus(v) for k, v in raw_statuses.items()},
                "task_results": {k: RunResult(**v) for k, v in raw_results.items()},
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }

    def list_runs(self) -> List[Dict[str, Any]]:
        """List all tracked orchestration runs."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT plan_id, goal, status, plan_file, created_at, updated_at "
                "FROM orchestration_runs ORDER BY updated_at DESC"
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]

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
            TaskStatus.PENDING: "⏳ PENDING",
            TaskStatus.RUNNING: "🔄 RUNNING",
            TaskStatus.VALIDATING: "🔍 VALIDATING",
            TaskStatus.COMPLETED: "✅ COMPLETED",
            TaskStatus.FAILED: "❌ FAILED",
            TaskStatus.BLOCKED: "🚫 BLOCKED",
            TaskStatus.SKIPPED: "⏭️ SKIPPED",
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
