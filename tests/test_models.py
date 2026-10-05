"""Unit tests for models."""

from harness_agent.core.models import AgyConfig, EvalReport, RunResult, Task, TaskCheck


def test_task_creation():
    task = Task(
        id="task_1",
        name="Test Task",
        prompt="Write a function",
        checks=[TaskCheck(type="file_exists", target="hello.py")],
    )
    assert task.id == "task_1"
    assert len(task.checks) == 1
    assert task.checks[0].type == "file_exists"


def test_agy_config_defaults():
    config = AgyConfig()
    assert config.executable_path == "agy"
    assert config.dangerously_skip_permissions is True
    assert config.output_format == "stream-json"


def test_eval_report_calculation():
    results = [
        RunResult(
            task_id="t1",
            success=True,
            exit_code=0,
            duration_seconds=1.5,
            output_text="done",
        ),
        RunResult(
            task_id="t2",
            success=False,
            exit_code=1,
            duration_seconds=2.0,
            error_message="failed",
        ),
    ]
    report = EvalReport(
        suite_name="test_suite",
        total_tasks=2,
        passed_tasks=1,
        failed_tasks=1,
        duration_seconds=3.5,
        pass_rate=50.0,
        results=results,
    )
    assert report.total_tasks == 2
    assert report.passed_tasks == 1
    assert report.pass_rate == 50.0
