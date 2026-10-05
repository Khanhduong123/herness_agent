"""Orchestrator PreInvocation enforcement hook.

Enforces RULE 0 (Zero-Tolerance Code-Writing Lock for Orchestrator)
by injecting an ephemeral reminder before each AI invocation.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

ORCHESTRATOR_RULE_0_REMINDER = (
    "🚨 CRITICAL REMINDER "
    "(RULE 0: ZERO-TOLERANCE CODE-WRITING LOCK FOR ORCHESTRATOR):\n"
    "When operating via agy or acting as the Central Orchestrator, "
    "YOU ARE STRICTLY PROHIBITED FROM DIRECTLY WRITING, MODIFYING, "
    "OR REFACTORING APPLICATION SOURCE CODE (src/, tests/, etc.).\n\n"
    "1. DO NOT touch application code directly. "
    "Calling replace_file_content, apply_patch, or write_to_file "
    "on application code files is a critical system violation.\n"
    "2. DO NOT write code yourself. Coding is exclusively the responsibility "
    "of a dedicated Coder Worker Agent.\n"
    "3. YOUR ORCHESTRATOR WORKFLOW IS STRICTLY:\n"
    "   - Decompose & Plan: Formulate a Task DAG with mandatory plan_id in "
    ".ai/plans/main/YYYY-MM-DD/main_[plan_id].md and Sub-Specs in "
    ".ai/plans/subtasks/YYYY-MM-DD/[plan_id]/subtask_01_[task_id].md.\n"
    "   - Wait for User Approval: Present the plan to the user "
    "before any workspace setup or worker launch.\n"
    "   - Setup Workspace: Create an isolated git worktree via Herdr "
    "(herdr worktree create --branch agent/<task_id>).\n"
    "   - Dispatch to Worker: Launch a specialized Coder Agent "
    "(herdr agent start worker_[task_id] --kind agy --pane <pane> "
    "or harness-agent orchestrate).\n"
    "   - Quality Gate & Critics: Dispatch diffs in parallel to "
    "the 3 Adversarial Critics and verify 100% pytest pass rate."
)


class EphemeralStep(BaseModel):
    """Step representation for an ephemeral message injected into context."""

    ephemeralMessage: str = Field(
        ...,
        description="Ephemeral reminder message injected into agent context.",
    )


class PreInvocationOutput(BaseModel):
    """Output structure conforming to PreInvocation hook contract."""

    injectSteps: List[EphemeralStep] = Field(
        default_factory=list,
        description="List of steps to inject before model invocation.",
    )


def get_rule_0_reminder() -> str:
    """Return the RULE 0 reminder text for the Orchestrator."""
    return ORCHESTRATOR_RULE_0_REMINDER


def build_preinvocation_payload(
    message: Optional[str] = None,
) -> PreInvocationOutput:
    """Build the PreInvocation hook output object."""
    reminder = message if message is not None else get_rule_0_reminder()
    return PreInvocationOutput(injectSteps=[EphemeralStep(ephemeralMessage=reminder)])


def main() -> None:
    """Entry point for the PreInvocation enforcement hook script."""
    input_data: Dict[str, Any] = {}
    try:
        if not sys.stdin.isatty():
            input_data = json.load(sys.stdin)
    except Exception:
        input_data = {}

    _ = input_data
    output = build_preinvocation_payload()
    print(output.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
