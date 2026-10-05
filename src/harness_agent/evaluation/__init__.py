"""Evaluation subpackage for task evaluation, diff patching, and adversarial critics."""

from __future__ import annotations

from harness_agent.evaluation.critics import (
    aggregate_critic_feedback,
    build_critic_prompt,
    detect_performance_issues,
    detect_requirement_issues,
    detect_security_issues,
    dispatch_parallel_critics,
    save_critic_report,
)
from harness_agent.evaluation.evaluator import (
    BaseEvaluator,
    CommandEvaluator,
    FileExistsEvaluator,
    PatchOnlyEvaluator,
    TextMatchEvaluator,
    ToolLockEvaluator,
    evaluate_task,
)
from harness_agent.evaluation.patch import (
    DisallowedFullFileOverwriteError,
    PatchHunk,
    PatchResult,
    ToolLockViolationError,
    apply_patch,
    apply_unified_diff,
    multi_replace_file_content,
    parse_unified_diff,
    validate_tool_call,
)

__all__ = [
    "BaseEvaluator",
    "CommandEvaluator",
    "DisallowedFullFileOverwriteError",
    "FileExistsEvaluator",
    "PatchHunk",
    "PatchOnlyEvaluator",
    "PatchResult",
    "TextMatchEvaluator",
    "ToolLockEvaluator",
    "ToolLockViolationError",
    "aggregate_critic_feedback",
    "apply_patch",
    "apply_unified_diff",
    "build_critic_prompt",
    "detect_performance_issues",
    "detect_requirement_issues",
    "detect_security_issues",
    "dispatch_parallel_critics",
    "evaluate_task",
    "multi_replace_file_content",
    "parse_unified_diff",
    "save_critic_report",
    "validate_tool_call",
]
