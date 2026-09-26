"""Evaluators for checking agent task outputs and workspace artifacts."""

from __future__ import annotations

import os
import re
import subprocess
from abc import ABC, abstractmethod
from typing import Dict, Tuple

from harness_agent.models import RunResult, Task, TaskCheck


class BaseEvaluator(ABC):
    """Abstract base class for all task evaluators."""

    @abstractmethod
    def evaluate(self, check: TaskCheck, result: RunResult, workspace_dir: str) -> Tuple[bool, str]:
        """Evaluate a check against the run result and workspace.

        Returns (passed, details).
        """
        pass


class FileExistsEvaluator(BaseEvaluator):
    """Checks whether a required file exists in the workspace."""

    def evaluate(self, check: TaskCheck, result: RunResult, workspace_dir: str) -> Tuple[bool, str]:
        target_path = os.path.join(workspace_dir, check.target)
        exists = os.path.exists(target_path)
        if exists:
            return True, f"File exists: {check.target}"
        return False, f"Missing expected file: {check.target} at {target_path}"


class TextMatchEvaluator(BaseEvaluator):
    """Checks whether the agent's output matches an expected regex or substring."""

    def evaluate(self, check: TaskCheck, result: RunResult, workspace_dir: str) -> Tuple[bool, str]:
        pattern = check.target
        if not pattern:
            return True, "Empty pattern, skipped"

        match = re.search(pattern, result.output_text, re.MULTILINE | re.IGNORECASE)
        if match:
            return True, f"Matched pattern '{pattern}' in output"
        return False, f"Pattern '{pattern}' not found in agent output text"


class CommandEvaluator(BaseEvaluator):
    """Runs a verification command (e.g. pytest, python script) to check correctness."""

    def evaluate(self, check: TaskCheck, result: RunResult, workspace_dir: str) -> Tuple[bool, str]:
        command = check.target
        try:
            res = subprocess.run(
                command,
                shell=True,
                cwd=workspace_dir,
                capture_output=True,
                text=True,
                timeout=60,
            )
            passed = res.returncode == 0
            if passed:
                return True, f"Command '{command}' passed with exit code 0"
            err_msg = res.stderr.strip() or res.stdout.strip()
            return (
                False,
                f"Command '{command}' failed (code {res.returncode}): {err_msg}",
            )
        except Exception as exc:
            return False, f"Failed to execute verification command '{command}': {exc}"


EVALUATOR_REGISTRY: Dict[str, BaseEvaluator] = {
    "file_exists": FileExistsEvaluator(),
    "text_match": TextMatchEvaluator(),
    "command_exit_zero": CommandEvaluator(),
}


def evaluate_task(task: Task, result: RunResult, workspace_dir: str) -> Dict[str, bool]:
    """Run all configured checks for a task and record outcomes in result.check_results."""
    check_results: Dict[str, bool] = {}
    all_passed = True

    for idx, check in enumerate(task.checks):
        evaluator = EVALUATOR_REGISTRY.get(check.type)
        key = f"{check.type}_{idx}_{check.target}"
        if evaluator is None:
            check_results[key] = False
            all_passed = False
            continue

        passed, _ = evaluator.evaluate(check, result, workspace_dir)
        check_results[key] = passed
        if not passed:
            all_passed = False

    result.check_results = check_results
    if task.checks and not all_passed:
        result.success = False

    return check_results
