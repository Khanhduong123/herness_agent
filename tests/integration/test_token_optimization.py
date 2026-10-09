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
