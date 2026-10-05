"""Unit tests for AgentHarness."""

from unittest.mock import AsyncMock

import pytest

from harness_agent.core.harness import AgentHarness
from harness_agent.core.models import AgyConfig, RunResult, Task


@pytest.mark.asyncio
async def test_run_suite_mocked():
    tasks = [
        Task(id="task_1", name="Task 1", prompt="Prompt 1"),
        Task(id="task_2", name="Task 2", prompt="Prompt 2"),
    ]

    mock_runner = AsyncMock()
    mock_runner.execute_task.side_effect = [
        RunResult(task_id="task_1", success=True, exit_code=0, duration_seconds=1.0),
        RunResult(task_id="task_2", success=False, exit_code=1, duration_seconds=1.2),
    ]

    harness = AgentHarness(config=AgyConfig(), runner=mock_runner)
    report = await harness.run_suite(suite_name="test_suite", tasks=tasks)

    assert report.total_tasks == 2
    assert report.passed_tasks == 1
    assert report.failed_tasks == 1
    assert report.pass_rate == 50.0
    assert len(report.results) == 2


def test_load_suite_from_yaml(tmp_path):
    yaml_content = """
tasks:
  - id: "sample_1"
    name: "Sample Task"
    prompt: "echo hello"
"""
    suite_file = tmp_path / "suite.yaml"
    suite_file.write_text(yaml_content, encoding="utf-8")

    tasks = AgentHarness.load_suite_from_yaml(str(suite_file))
    assert len(tasks) == 1
    assert tasks[0].id == "sample_1"
    assert tasks[0].prompt == "echo hello"
