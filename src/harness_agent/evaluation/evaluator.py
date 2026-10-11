"""Evaluators for checking agent task outputs and workspace artifacts."""

from __future__ import annotations

import json
import os
import re
import subprocess
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

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


class CoverageGateEvaluator(BaseEvaluator):
    """Evaluates whether the agent test output meets a minimum test coverage percentage."""

    def evaluate(self, check: TaskCheck, result: RunResult, workspace_dir: str) -> Tuple[bool, str]:
        # Threshold can be passed in check.expected (or check.target)
        threshold = 80.0
        if check.expected is not None:
            try:
                threshold = float(check.expected)
            except (ValueError, TypeError):
                pass
        elif check.target:
            try:
                threshold = float(check.target)
            except (ValueError, TypeError):
                pass

        summary = parse_coverage_report(result.output_text)
        try:
            passed = evaluate_coverage_gate(summary, threshold=threshold)
            return (
                passed,
                f"Coverage gate passed ({summary.total_coverage:.2f}% >= {threshold:.2f}%)",
            )
        except CoverageQualityGateError as err:
            return False, str(err)


EVALUATOR_REGISTRY: Dict[str, BaseEvaluator] = {
    "file_exists": FileExistsEvaluator(),
    "text_match": TextMatchEvaluator(),
    "command_exit_zero": CommandEvaluator(),
    "patch_only": PatchOnlyEvaluator(),
    "tool_lock": ToolLockEvaluator(),
    "coverage_gate": CoverageGateEvaluator(),
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


class CoverageQualityGateError(Exception):
    """Raised when test coverage fails to meet the required quality gate threshold."""

    def __init__(self, message: str, coverage: CoverageSummary):
        super().__init__(message)
        self.coverage = coverage


class CoverageSummary(BaseModel):
    total_coverage: float = Field(..., ge=0.0, le=100.0)
    missed_lines_by_file: Dict[str, List[str]] = Field(default_factory=dict)
    passed: bool = False


def parse_coverage_report(cov_output: str) -> CoverageSummary:
    """Parses stdout/json from pytest --cov --cov-report=json or standard text summary table.

    Computes total line coverage percentage and maps uncovered line ranges per file.
    """
    if not cov_output or not cov_output.strip():
        return CoverageSummary(total_coverage=0.0, missed_lines_by_file={}, passed=False)

    text = cov_output.strip()

    # 1. Attempt JSON parsing if JSON format is present
    # Could be pure JSON or JSON embedded within text
    json_candidates = []
    if "{" in text and "}" in text:
        # Check if the whole text is json
        try:
            data = json.loads(text)
            json_candidates.append(data)
        except Exception:
            # Try to extract the outer {...} substring
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    data = json.loads(text[start : end + 1])
                    json_candidates.append(data)
                except Exception:
                    pass

    for data in json_candidates:
        if isinstance(data, dict) and "totals" in data:
            totals = data.get("totals", {})
            percent_covered = totals.get("percent_covered", 0.0)
            if percent_covered is not None:
                total_cov = round(float(percent_covered), 2)
            else:
                total_cov = 0.0

            missed_map: Dict[str, List[str]] = {}
            files_dict = data.get("files", {})
            for fname, finfo in files_dict.items():
                missing_lines = finfo.get("missing_lines", [])
                if missing_lines:
                    # Group missing lines into contiguous ranges or strings
                    ranges: List[str] = []
                    start_num = missing_lines[0]
                    prev_num = missing_lines[0]
                    for num in missing_lines[1:]:
                        if num == prev_num + 1:
                            prev_num = num
                        else:
                            ranges.append(
                                f"{start_num}-{prev_num}"
                                if start_num != prev_num
                                else str(start_num)
                            )
                            start_num = num
                            prev_num = num
                    ranges.append(
                        f"{start_num}-{prev_num}" if start_num != prev_num else str(start_num)
                    )
                    missed_map[fname] = ranges

            return CoverageSummary(
                total_coverage=min(max(total_cov, 0.0), 100.0),
                missed_lines_by_file=missed_map,
                passed=(total_cov >= 80.0),
            )

    # 2. Text table parsing (standard pytest-cov output)
    # Example format:
    # ---------- coverage: platform ... -----------
    # Name                      Stmts   Miss  Cover   Missing
    # -------------------------------------------------------
    # src/foo.py                   10      2    80%   12-13
    # src/bar.py                   20      0   100%
    # -------------------------------------------------------
    # TOTAL                        30      2    93%
    missed_by_file: Dict[str, List[str]] = {}
    total_cov_found: Optional[float] = None

    lines = text.splitlines()

    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue

        if re.match(r"^Name\s+Stmts\s+Miss", line_clean, re.IGNORECASE):
            continue

        if re.match(r"^-+$", line_clean):
            continue

        # Look for TOTAL line
        total_match = re.search(
            r"\bTOTAL\s+\d+\s+\d+(?:\s+\d+\s+\d+)?\s+(\d+(?:\.\d+)?)%", line_clean, re.IGNORECASE
        )
        if total_match:
            try:
                total_cov_found = float(total_match.group(1))
            except ValueError:
                pass
            continue

        # Look for file line
        # e.g., src/foo.py  10  2  80%  12-13, 25
        # or src/harness_agent/evaluator.py  100  15  85%  12-14, 25-30
        file_match = re.match(
            r"^(\S+\.py)\s+\d+\s+(\d+)(?:\s+\d+\s+\d+)?\s+(\d+(?:\.\d+)?)%(?:\s+(.+))?$",
            line_clean,
        )
        if file_match:
            filename = file_match.group(1)
            miss_count = int(file_match.group(2))
            missing_ranges_str = file_match.group(4)
            if miss_count > 0 and missing_ranges_str:
                parts = [p.strip() for p in missing_ranges_str.split(",") if p.strip()]
                missed_by_file[filename] = parts

    # Fallback search if TOTAL line wasn't matched standardly
    if total_cov_found is None:
        alt_match = re.search(r"TOTAL\b.*?(\d+(?:\.\d+)?)%", text, re.IGNORECASE)
        if alt_match:
            try:
                total_cov_found = float(alt_match.group(1))
            except ValueError:
                pass

    if total_cov_found is None:
        # Fallback: check if any coverage percentage is reported
        cov_pct = re.search(r"(\d+(?:\.\d+)?)%\s*coverage", text, re.IGNORECASE)
        if cov_pct:
            try:
                total_cov_found = float(cov_pct.group(1))
            except ValueError:
                pass

    final_cov = total_cov_found if total_cov_found is not None else 0.0
    final_cov = min(max(final_cov, 0.0), 100.0)

    return CoverageSummary(
        total_coverage=final_cov,
        missed_lines_by_file=missed_by_file,
        passed=(final_cov >= 80.0),
    )


def build_coverage_gap_prompt(coverage: CoverageSummary) -> str:
    """Generates an actionable feedback prompt detailing uncovered functions and lines.

    Instructs worker agents to add targeted assertions covering the missed branches.
    """

    lines = [
        f"Coverage Quality Gate Status: {'PASSED' if coverage.passed else 'FAILED'}",
        f"Total Coverage: {coverage.total_coverage:.2f}% (Threshold: 80.0%)",
        "",
    ]
    if coverage.missed_lines_by_file:
        lines.append("The following files have uncovered lines / missing test branches:")
        for file_path, missed in coverage.missed_lines_by_file.items():
            missed_desc = ", ".join(missed)
            lines.append(f"  - `{file_path}`: lines {missed_desc}")
        lines.append("")
        lines.append(
            "Action Required: Please write unit tests covering the missed branches and lines above "
            "to bring total coverage to at least 80.0%."
        )
    else:
        lines.append("All statements and branches are fully covered by unit tests.")

    return "\n".join(lines)


def evaluate_coverage_gate(
    coverage: CoverageSummary,
    threshold: float = 80.0,
) -> bool:
    """Validates that test suite coverage meets or exceeds the required threshold.

    Args:
        coverage (CoverageSummary): Parsed coverage summary model.
        threshold (float): Minimum acceptable coverage percentage (default 80.0).

    Returns:
        bool: True if coverage satisfies the threshold, False otherwise.

    Raises:
        CoverageQualityGateError: If coverage is below the required threshold.
    """
    if coverage.total_coverage >= threshold:
        coverage.passed = True
        return True

    coverage.passed = False
    gap_prompt = build_coverage_gap_prompt(coverage)
    msg = (
        f"Coverage quality gate failed: {coverage.total_coverage:.2f}% < {threshold:.2f}%\n"
        f"{gap_prompt}"
    )
    raise CoverageQualityGateError(
        msg,
        coverage=coverage,
    )
