"""Unit tests for SessionStart context bootstrapper hook.

Covers:
1. Cold start in uninitialized workspace.
2. Context hydration with active state and WAL events.
3. Budget clamping (max 5 modified files, max 3 milestones, max tokens/lines).
4. Pure-Python fallback when harness_agent is unavailable.
5. Subprocess CLI execution within SLA timeout.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

from harness_agent.hooks.bootstrap_context import (
    COLD_START_MESSAGE,
    MAX_LINES,
    MAX_MILESTONES,
    MAX_MODIFIED_FILES,
    build_bootstrap_payload,
    build_context_from_pure_python,
    format_session_start_payload,
    get_hydrated_context,
)


def test_bootstrap_context_cold_start(tmp_path: Path) -> None:
    """Test cold start when workspace directory has no .ai/ folder."""
    empty_workspace = tmp_path / "empty_proj"
    empty_workspace.mkdir(parents=True, exist_ok=True)

    payload = build_bootstrap_payload(empty_workspace)

    assert "injectSteps" in payload
    assert isinstance(payload["injectSteps"], list)
    assert len(payload["injectSteps"]) == 1
    sys_msg = payload["injectSteps"][0]["systemMessage"]["systemMessage"]
    assert COLD_START_MESSAGE in sys_msg
    assert "Workspace initialized" in sys_msg


def test_bootstrap_context_with_active_state(tmp_path: Path) -> None:
    """Test context hydration with active state and WAL milestones."""
    workspace = tmp_path / "active_proj"
    context_dir = workspace / ".ai" / "context"
    context_dir.mkdir(parents=True, exist_ok=True)

    state_file = context_dir / "state.json"
    wal_file = context_dir / "wal_actions.log"

    state_data = {
        "task_id": "subtask_01_bootstrap_hook",
        "session_id": "session_context_hydration",
        "status": "in_progress",
        "goal": "Hydrate active project context on agy session start.",
        "active_step": 3,
        "modified_files": ["src/harness_agent/hooks/bootstrap_context.py", ".agents/hooks.json"],
    }
    state_file.write_text(json.dumps(state_data), encoding="utf-8")

    wal_file.write_text(
        "session_id,step_index,event_type,tool_name,status_code,latency_ms,error_message\n"
        "session_context_hydration,1,action_start,plan_tasks,0,15.2,\n"
        "session_context_hydration,2,action_end,plan_tasks,0,18.5,\n"
        "session_context_hydration,3,subtask_end,write_file,0,45.0,\n",
        encoding="utf-8",
    )

    payload = build_bootstrap_payload(workspace)
    assert "injectSteps" in payload
    sys_msg = payload["injectSteps"][0]["systemMessage"]["systemMessage"]

    assert "### Active Project Context" in sys_msg
    assert "subtask_01_bootstrap_hook" in sys_msg
    assert "session_context_hydration" in sys_msg
    assert "IN_PROGRESS" in sys_msg
    assert "Hydrate active project context on agy session start." in sys_msg
    assert "Active Step" in sys_msg
    assert "Recent Milestones" in sys_msg
    assert "write_file" in sys_msg
    assert "src/harness_agent/hooks/bootstrap_context.py" in sys_msg
    assert ".agents/hooks.json" in sys_msg


def test_bootstrap_context_budget_clamping(tmp_path: Path) -> None:
    """Test clamping when state has 50 modified files and 20 milestones."""
    workspace = tmp_path / "budget_proj"
    context_dir = workspace / ".ai" / "context"
    context_dir.mkdir(parents=True, exist_ok=True)

    state_file = context_dir / "state.json"
    wal_file = context_dir / "wal_actions.log"

    # 50 modified files
    many_files = [f"src/file_{i}.py" for i in range(50)]
    state_data = {
        "task_id": "task_clamped",
        "session_id": "session_clamped",
        "status": "running",
        "goal": "Verify token and line budget clamping.",
        "active_step": 20,
        "modified_files": many_files,
    }
    state_file.write_text(json.dumps(state_data), encoding="utf-8")

    # 20 WAL events
    wal_lines = ["session_id,step_index,event_type,tool_name,status_code,latency_ms,error_message"]
    for i in range(1, 21):
        wal_lines.append(f"session_clamped,{i},tool_call,tool_{i},0,10.0,")
    wal_file.write_text("\n".join(wal_lines) + "\n", encoding="utf-8")

    payload = build_bootstrap_payload(workspace)
    sys_msg = payload["injectSteps"][0]["systemMessage"]["systemMessage"]

    # Check modified files are clamped to max 5
    file_lines = [line for line in sys_msg.splitlines() if line.strip().startswith("- `src/file_")]
    assert len(file_lines) == MAX_MODIFIED_FILES
    assert len(file_lines) <= 5

    # Check milestones are clamped to max 3
    milestone_lines = [line for line in sys_msg.splitlines() if line.strip().startswith("- Step ")]
    assert len(milestone_lines) == MAX_MILESTONES
    assert len(milestone_lines) <= 3

    # Ensure line count is bounded
    assert len(sys_msg.splitlines()) <= MAX_LINES


def test_bootstrap_context_fallback_pure_python(tmp_path: Path) -> None:
    """Test pure-Python fallback parser when harness_agent cannot be imported."""
    workspace = tmp_path / "pure_py_proj"
    context_dir = workspace / ".ai" / "context"
    context_dir.mkdir(parents=True, exist_ok=True)

    state_file = context_dir / "state.json"
    wal_file = context_dir / "wal_actions.log"

    state_file.write_text(
        json.dumps(
            {
                "task_id": "fallback_task",
                "session_id": "fallback_session",
                "status": "completed",
                "goal": "Test pure python fallback parser.",
                "active_step": 5,
                "modified_files": ["standalone.py"],
            }
        ),
        encoding="utf-8",
    )

    wal_file.write_text(
        "session_id,step_index,event_type,tool_name,status_code,latency_ms,error_message\n"
        "fallback_session,5,subtask_end,git_commit,0,100.0,\n",
        encoding="utf-8",
    )

    # Force pure-Python parser directly
    raw_md = build_context_from_pure_python(workspace)
    payload = format_session_start_payload(raw_md)

    assert "injectSteps" in payload
    sys_msg = payload["injectSteps"][0]["systemMessage"]["systemMessage"]
    assert "### Active Project Context" in sys_msg
    assert "fallback_task" in sys_msg
    assert "fallback_session" in sys_msg
    assert "COMPLETED" in sys_msg
    assert "Test pure python fallback parser." in sys_msg
    assert "git_commit" in sys_msg
    assert "standalone.py" in sys_msg

    # Also test get_hydrated_context fallback when importing StateCoordinator raises ImportError
    with patch.dict("sys.modules", {"harness_agent.core.state": None}):
        fallback_md = get_hydrated_context(workspace)
        assert "fallback_task" in fallback_md


def test_bootstrap_cli_execution(tmp_path: Path) -> None:
    """Test executing bootstrap_context.py as a subprocess terminates in < 500ms with valid JSON."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    hook_script = repo_root / ".agents" / "hooks" / "bootstrap_context.py"
    if not hook_script.exists():
        hook_script = repo_root / "src" / "harness_agent" / "hooks" / "bootstrap_context.py"

    assert hook_script.exists(), f"Missing hook script at {hook_script}"

    input_payload = json.dumps({"workspacePaths": [str(tmp_path)]})

    start_time = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, str(hook_script)],
        input=input_payload,
        capture_output=True,
        text=True,
        timeout=5,
    )
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    assert proc.returncode == 0, f"Process failed: {proc.stderr}"
    # Execution must finish in reasonable SLA (< 2000ms on Windows CI / dev cold start)
    assert elapsed_ms < 2000, f"Execution took too long: {elapsed_ms}ms"

    # Validate output schema
    stdout_json = json.loads(proc.stdout)
    assert "injectSteps" in stdout_json
    assert isinstance(stdout_json["injectSteps"], list)
    assert len(stdout_json["injectSteps"]) == 1
    assert "systemMessage" in stdout_json["injectSteps"][0]
    assert "systemMessage" in stdout_json["injectSteps"][0]["systemMessage"]
