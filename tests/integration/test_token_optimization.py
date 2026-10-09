"""Integration tests for token optimization and runner log.csv recording."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness_agent.core.models import AgyConfig, Task
from harness_agent.core.runner import AgyRunner
from harness_agent.core.token_logger import TokenLogger


@pytest.mark.asyncio
async def test_runner_token_capture_and_logging(tmp_path: Path, monkeypatch):
    """TC-04: End-to-end runner token capture from stream-json events."""
    custom_csv = tmp_path / "custom_log.csv"
    monkeypatch.setattr(TokenLogger, "DEFAULT_CSV_PATH", custom_csv)

    runner = AgyRunner(
        config=AgyConfig(
            model="gemini-1.5-flash",
            output_format="stream-json",
        )
    )

    task = Task(
        id="task_int_token_01",
        name="Integration Token Test",
        prompt="Synthesize summary",
    )

    events_stream = (
        json.dumps({"type": "text", "text": "Processing start...\n"})
        + "\n"
        + json.dumps(
            {
                "type": "usage",
                "prompt_tokens": 1500,
                "completion_tokens": 300,
                "cached_tokens": 500,
            }
        )
        + "\n"
        + json.dumps({"type": "text", "text": "Finished task.\n"})
    )

    class DummyProcess:
        returncode = 0

        async def communicate(self):
            return events_stream.encode("utf-8"), b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        return DummyProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    result = await runner.execute_task(task)

    assert result.success is True
    assert result.prompt_tokens == 1500
    assert result.completion_tokens == 300
    assert result.cached_tokens == 500
    assert result.total_tokens == 1800
    assert result.estimated_cost_usd > 0.0

    assert custom_csv.exists()
    summary = TokenLogger.compute_summary(custom_csv)
    assert summary["total_runs"] == 1
    assert summary["prompt_tokens"] == 1500
    assert summary["completion_tokens"] == 300
    assert summary["cached_tokens"] == 500
    assert summary["total_tokens"] == 1800
    assert summary["total_cost_usd"] == pytest.approx(result.estimated_cost_usd, rel=1e-5)


def test_wait_for_task_telemetry_logging(tmp_path: Path):
    """TC-05: Verify wait_for_task parses YAML telemetry and writes to .runs/log.csv."""
    import csv

    from harness_agent.core.dispatch import HerdrDispatcher

    status_dir = tmp_path / ".ai" / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = tmp_path / ".runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    telemetry_content = """status: COMPLETED
plan_id: plan_token_opt_e2e
task_id: subtask_08_e2e
role: coder
model: gemini-1.5-flash
prompt_tokens: 25000
completion_tokens: 1500
cached_tokens: 8000
truncated_tokens: 500
"""
    complete_flag = status_dir / "subtask_08_e2e.complete"
    complete_flag.write_text(telemetry_content, encoding="utf-8")

    ok, msg = HerdrDispatcher.wait_for_task(
        task_id="subtask_08_e2e",
        timeout_seconds=5,
        status_dir=status_dir,
        repo_root=tmp_path,
    )

    assert ok is True
    assert "status: COMPLETED" in msg

    log_csv = runs_dir / "log.csv"
    assert log_csv.exists()

    with open(log_csv, mode="r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 1
        row = reader[0]
        assert row["plan_id"] == "plan_token_opt_e2e"
        assert row["task_id"] == "subtask_08_e2e"
        assert row["role"] == "coder"
        assert row["model"] == "gemini-1.5-flash"
        assert row["prompt_tokens"] == "25000"
        assert row["completion_tokens"] == "1500"
        assert row["cached_tokens"] == "8000"
        assert row["total_tokens"] == "26500"
        assert row["truncated_output_tokens"] == "500"
        assert float(row["estimated_cost_usd"]) > 0.0
        assert float(row["total_savings_usd"]) > 0.0
        assert row["status"] == "COMPLETED"


def test_wait_for_task_legacy_plain_text(tmp_path: Path):
    """TC-06: Verify wait_for_task handles legacy plain text without error."""
    import csv

    from harness_agent.core.dispatch import HerdrDispatcher

    status_dir = tmp_path / ".ai" / "status"
    status_dir.mkdir(parents=True, exist_ok=True)

    complete_flag = status_dir / "legacy_task.complete"
    complete_flag.write_text("[WORKER_COMPLETED]", encoding="utf-8")

    ok, msg = HerdrDispatcher.wait_for_task(
        task_id="legacy_task",
        timeout_seconds=5,
        status_dir=status_dir,
        repo_root=tmp_path,
    )

    assert ok is True
    assert msg == "[WORKER_COMPLETED]"

    log_csv = tmp_path / ".runs" / "log.csv"
    assert log_csv.exists()
    with open(log_csv, mode="r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 1
        row = reader[0]
        assert row["task_id"] == "legacy_task"
        assert row["prompt_tokens"] == "0"
        assert row["completion_tokens"] == "0"
        assert row["total_tokens"] == "0"
        assert row["status"] == "COMPLETED"


def test_wait_for_task_preserves_telemetry_or_active_model(tmp_path: Path, monkeypatch):
    """TC-05: wait_for_task uses active model when model is missing from telemetry."""
    import csv

    from harness_agent.core.dispatch import HerdrDispatcher

    monkeypatch.setenv("AGY_MODEL", "gemini-3.8-flash")

    status_dir = tmp_path / ".ai" / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = tmp_path / ".runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    telemetry_content = """status: COMPLETED
plan_id: plan_model_selection
task_id: subtask_model_test
prompt_tokens: 12000
completion_tokens: 800
cached_tokens: 4000
"""
    complete_flag = status_dir / "subtask_model_test.complete"
    complete_flag.write_text(telemetry_content, encoding="utf-8")

    ok, msg = HerdrDispatcher.wait_for_task(
        task_id="subtask_model_test",
        timeout_seconds=5,
        status_dir=status_dir,
        repo_root=tmp_path,
    )

    assert ok is True
    log_csv = runs_dir / "log.csv"
    assert log_csv.exists()

    with open(log_csv, mode="r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 1
        row = reader[0]
        assert row["task_id"] == "subtask_model_test"
        assert row["model"] == "gemini-3.8-flash"


@pytest.mark.asyncio
async def test_orchestrator_multi_critic_consolidated_log(tmp_path: Path, monkeypatch):
    """TC-01: Orchestrated plan with critics logs 1 consolidated record with cumulative metrics."""
    import csv
    from unittest.mock import AsyncMock

    from harness_agent.core.models import (
        AgentRole,
        AggregatedCriticReview,
        CriticFeedback,
        OrchestrationPlan,
        RunResult,
        SubTask,
    )
    from harness_agent.core.orchestrator import AgentOrchestrator

    custom_csv = tmp_path / ".runs" / "log.csv"
    monkeypatch.setattr(TokenLogger, "DEFAULT_CSV_PATH", custom_csv)

    plan = OrchestrationPlan(
        plan_id="plan_consolidated_test",
        goal="Verify consolidated metrics",
        enable_adversarial_critics=True,
        tasks=[
            SubTask(
                id="task_coder_01",
                name="Coder Task",
                role=AgentRole.CODER,
                instruction="Implement feature",
            )
        ],
    )

    coder_res = RunResult(
        task_id="task_coder_01",
        success=True,
        exit_code=0,
        duration_seconds=2.5,
        output_text="Code changes applied.",
        prompt_tokens=1000,
        completion_tokens=200,
        cached_tokens=300,
        estimated_cost_usd=0.002,
    )

    critic_sec_res = RunResult(
        task_id="critic_sec",
        success=True,
        exit_code=0,
        duration_seconds=1.0,
        prompt_tokens=500,
        completion_tokens=50,
        cached_tokens=100,
        estimated_cost_usd=0.0008,
    )
    critic_perf_res = RunResult(
        task_id="critic_perf",
        success=True,
        exit_code=0,
        duration_seconds=1.2,
        prompt_tokens=600,
        completion_tokens=60,
        cached_tokens=150,
        estimated_cost_usd=0.0009,
    )
    critic_req_res = RunResult(
        task_id="critic_req",
        success=True,
        exit_code=0,
        duration_seconds=0.8,
        prompt_tokens=400,
        completion_tokens=40,
        cached_tokens=80,
        estimated_cost_usd=0.0006,
    )

    review = AggregatedCriticReview(
        approved=True,
        critics_feedback={
            AgentRole.SECURITY_REVIEWER.value: CriticFeedback(
                role=AgentRole.SECURITY_REVIEWER,
                critic_name="security-critic",
                approved=True,
                run_result=critic_sec_res,
            ),
            AgentRole.PERFORMANCE_REVIEWER.value: CriticFeedback(
                role=AgentRole.PERFORMANCE_REVIEWER,
                critic_name="performance-critic",
                approved=True,
                run_result=critic_perf_res,
            ),
            AgentRole.REQUIREMENT_REVIEWER.value: CriticFeedback(
                role=AgentRole.REQUIREMENT_REVIEWER,
                critic_name="requirement-critic",
                approved=True,
                run_result=critic_req_res,
            ),
        },
    )

    orchestrator = AgentOrchestrator(base_config=AgyConfig(model="gemini-2.5-pro"))
    mock_runner = AsyncMock()
    mock_runner.execute_task.return_value = coder_res
    monkeypatch.setattr(
        "harness_agent.core.orchestrator.AgyRunner.execute_task", mock_runner.execute_task
    )
    monkeypatch.setattr(
        orchestrator,
        "dispatch_adversarial_critics",
        AsyncMock(return_value=review),
    )

    result = await orchestrator.run_plan(plan)
    assert result.success is True

    # Validate CSV emission
    assert custom_csv.exists()
    with open(custom_csv, mode="r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    row = rows[0]
    assert row["task_id"] == "task_coder_01"
    assert row["plan_id"] == "plan_consolidated_test"
    assert row["status"] == "COMPLETED"
    assert int(row["prompt_tokens"]) == 1000 + 500 + 600 + 400
    assert int(row["completion_tokens"]) == 200 + 50 + 60 + 40
    assert int(row["cached_tokens"]) == 300 + 100 + 150 + 80
    assert float(row["duration_seconds"]) == pytest.approx(2.5 + 1.0 + 1.2 + 0.8, rel=1e-2)


@pytest.mark.asyncio
async def test_orchestrator_critic_rejection_marks_failed_with_cumulative_metrics(
    tmp_path: Path, monkeypatch
):
    """TC-02: When a critic rejects, consolidated row status is FAILED with cumulative costs."""
    import csv
    from unittest.mock import AsyncMock

    from harness_agent.core.models import (
        AgentRole,
        AggregatedCriticReview,
        CriticFeedback,
        OrchestrationPlan,
        RunResult,
        SubTask,
    )
    from harness_agent.core.orchestrator import AgentOrchestrator

    custom_csv = tmp_path / ".runs" / "log.csv"
    monkeypatch.setattr(TokenLogger, "DEFAULT_CSV_PATH", custom_csv)

    plan = OrchestrationPlan(
        plan_id="plan_rejected_test",
        goal="Verify rejected critic consolidated metrics",
        enable_adversarial_critics=True,
        tasks=[
            SubTask(
                id="task_coder_reject",
                name="Coder Task",
                role=AgentRole.CODER,
                instruction="Implement flawed code",
            )
        ],
    )

    coder_res = RunResult(
        task_id="task_coder_reject",
        success=True,
        exit_code=0,
        duration_seconds=3.0,
        output_text="Code written with flaw.",
        prompt_tokens=800,
        completion_tokens=150,
        cached_tokens=200,
        estimated_cost_usd=0.0015,
    )

    critic_sec_res = RunResult(
        task_id="critic_sec_fail",
        success=True,
        exit_code=0,
        duration_seconds=1.5,
        prompt_tokens=700,
        completion_tokens=80,
        cached_tokens=100,
        estimated_cost_usd=0.0012,
    )

    review = AggregatedCriticReview(
        approved=False,
        critics_feedback={
            AgentRole.SECURITY_REVIEWER.value: CriticFeedback(
                role=AgentRole.SECURITY_REVIEWER,
                critic_name="security-critic",
                approved=False,
                issues=["SQL Injection detected"],
                run_result=critic_sec_res,
            )
        },
    )

    orchestrator = AgentOrchestrator(base_config=AgyConfig(model="gemini-2.5-pro"))
    mock_runner = AsyncMock()
    mock_runner.execute_task.return_value = coder_res
    monkeypatch.setattr(
        "harness_agent.core.orchestrator.AgyRunner.execute_task", mock_runner.execute_task
    )
    monkeypatch.setattr(
        orchestrator,
        "dispatch_adversarial_critics",
        AsyncMock(return_value=review),
    )

    result = await orchestrator.run_plan(plan)
    assert result.success is False

    assert custom_csv.exists()
    with open(custom_csv, mode="r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    row = rows[0]
    assert row["task_id"] == "task_coder_reject"
    assert row["status"] == "FAILED"
    assert int(row["prompt_tokens"]) == 800 + 700
    assert int(row["completion_tokens"]) == 150 + 80
    assert float(row["estimated_cost_usd"]) > 0.0
