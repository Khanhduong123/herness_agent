"""Unit tests for evaluators."""

from harness_agent.evaluator import (
    CommandEvaluator,
    FileExistsEvaluator,
    TextMatchEvaluator,
    evaluate_task,
)
from harness_agent.models import RunResult, Task, TaskCheck


def test_file_exists_evaluator(tmp_path):
    test_file = tmp_path / "result.txt"
    test_file.write_text("ok", encoding="utf-8")

    evaluator = FileExistsEvaluator()
    check = TaskCheck(type="file_exists", target="result.txt")
    res = RunResult(task_id="t1", success=True, exit_code=0, duration_seconds=0.1)

    passed, msg = evaluator.evaluate(check, res, str(tmp_path))
    assert passed is True
    assert "File exists" in msg

    check_missing = TaskCheck(type="file_exists", target="non_existent.txt")
    passed_missing, msg_missing = evaluator.evaluate(check_missing, res, str(tmp_path))
    assert passed_missing is False


def test_text_match_evaluator():
    evaluator = TextMatchEvaluator()
    check = TaskCheck(type="text_match", target=r"result:\s*\d+")
    res = RunResult(
        task_id="t1",
        success=True,
        exit_code=0,
        duration_seconds=0.1,
        output_text="The computed result: 42 is correct.",
    )

    passed, _ = evaluator.evaluate(check, res, ".")
    assert passed is True

    failed_check = TaskCheck(type="text_match", target="error")
    passed_f, _ = evaluator.evaluate(failed_check, res, ".")
    assert passed_f is False


def test_evaluate_task_aggregation(tmp_path):
    file_path = tmp_path / "output.log"
    file_path.write_text("Hello world", encoding="utf-8")

    task = Task(
        id="t_agg",
        name="Aggregate Test",
        prompt="do something",
        checks=[
            TaskCheck(type="file_exists", target="output.log"),
            TaskCheck(type="text_match", target="Hello"),
        ],
    )
    result = RunResult(
        task_id="t_agg",
        success=True,
        exit_code=0,
        duration_seconds=0.5,
        output_text="Hello from agent",
    )

    checks = evaluate_task(task, result, str(tmp_path))
    assert len(checks) == 2
    assert all(checks.values())
    assert result.success is True


def test_command_evaluator(tmp_path):
    evaluator = CommandEvaluator()
    check = TaskCheck(type="command_exit_zero", target="python -c \"print('test')\"")
    res = RunResult(task_id="t1", success=True, exit_code=0, duration_seconds=0.1)

    passed, msg = evaluator.evaluate(check, res, str(tmp_path))
    assert passed is True
    assert "exit code 0" in msg
