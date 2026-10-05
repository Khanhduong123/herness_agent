"""Evaluators for checking agent task outputs and workspace artifacts."""

from __future__ import annotations

import os
import re
import subprocess
from abc import ABC, abstractmethod
from typing import Dict, Tuple

from harness_agent.core.models import RunResult, Task, TaskCheck


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


class PatchOnlyEvaluator(BaseEvaluator):
    """Checks that the agent followed the 'Patch, never regenerate' rule.

    Validates that:
    1. The output contains diff hunks or unified diff headers (e.g. @@ ... @@).
    2. No full-file overwrite tool calls were performed on existing files.
    3. The changes are minimal diff patches rather than whole-file regenerations.
    """

    def evaluate(self, check: TaskCheck, result: RunResult, workspace_dir: str) -> Tuple[bool, str]:
        # Check tool calls first
        for tc in result.tool_calls:
            if tc.name in ("write_to_file", "write_file", "create_file"):
                target_file = (
                    tc.args.get("target_file") or tc.args.get("TargetFile") or tc.args.get("path")
                )
                if target_file:
                    target_path = (
                        os.path.join(workspace_dir, target_file)
                        if not os.path.isabs(target_file)
                        else target_file
                    )
                    if os.path.exists(target_path):
                        return False, (
                            f"Agent used disallowed full-file write tool '{tc.name}' "
                            f"on existing file '{target_file}'"
                        )

        # Check output text for diff hunks or patch content
        output = result.output_text
        diff_pattern = r"(@@\s+-\d+.*?\+\d+.*?@@|--- [ab]/.+\n\+\+\+ [ab]/.+)"
        has_diff = bool(re.search(diff_pattern, output, re.MULTILINE))

        # Check if tool calls contain patch tools
        has_patch_tool = any(
            tc.name in ("apply_patch", "replace_file_content", "multi_replace_file_content")
            for tc in result.tool_calls
        )

        if not (has_diff or has_patch_tool):
            return False, (
                "Output does not contain diff hunks or patch tool calls "
                "(Patch, never regenerate rule violated)"
            )

        return True, "Output complies with Patch-Only policy"


class ToolLockEvaluator(BaseEvaluator):
    """Validates that all executed tool calls comply with configured tool-locking policies."""

    def evaluate(self, check: TaskCheck, result: RunResult, workspace_dir: str) -> Tuple[bool, str]:
        from harness_agent.evaluation.patch import validate_tool_call

        disallowed = (
            [t.strip() for t in check.target.split(",") if t.strip()] if check.target else []
        )
        role = check.expected if isinstance(check.expected, str) else None
        for tc in result.tool_calls:
            valid, reason = validate_tool_call(
                tool_name=tc.name,
                args=tc.args,
                workspace_dir=workspace_dir,
                role=role,
                disallowed_tools=disallowed,
                enforce_patch_only=True,
            )
            if not valid:
                return False, f"ToolLock violation: {reason}"

        return True, "All tool calls satisfied tool-locking policies"


EVALUATOR_REGISTRY: Dict[str, BaseEvaluator] = {
    "file_exists": FileExistsEvaluator(),
    "text_match": TextMatchEvaluator(),
    "command_exit_zero": CommandEvaluator(),
    "patch_only": PatchOnlyEvaluator(),
    "tool_lock": ToolLockEvaluator(),
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
