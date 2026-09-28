"""Adversarial Critics: Specialized parallel reviewers."""

from __future__ import annotations

import asyncio
import re
from typing import Dict, List, Optional

from harness_agent.models import (
    AgentRole,
    AggregatedCriticReview,
    AgyConfig,
    CriticFeedback,
    OrchestrationPlan,
    RunResult,
    SubTask,
    Task,
    WorkerAgentConfig,
)
from harness_agent.runner import AgyRunner


def detect_security_issues(diff_or_code: str) -> List[str]:
    """Detect security vulnerabilities: SQL injection, command injection, leaked secrets."""
    issues: List[str] = []

    # 1. SQL Injection patterns:
    sql_patterns = [
        (
            r"""(?i)(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+.*"""
            r"""(?:f["'].*\{.*\}["']|["'].*\{.*\}["']\s*\.format|\%\s*\(?[\w_]+)""",
            "SQL Injection risk: Dynamic formatting detected inside SQL query string.",
        ),
        (
            r"""(?i)f["'].*(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+.*\{[\w_]+\}.*["']""",
            "SQL Injection risk: User variable directly interpolated into SQL query via f-string.",
        ),
        (
            r"""(?i)cursor\.execute\(\s*f["'].*\{[\w_]+\}.*["']\s*\)""",
            "SQL Injection risk: Unsanitized variable interpolated directly in cursor.execute().",
        ),
        (
            r"""(?i)(?:SELECT|INSERT|UPDATE|DELETE)\s+.*["']\s*\+\s*[\w_]+""",
            "SQL Injection risk: String concatenation in SQL statement.",
        ),
    ]

    for pattern, description in sql_patterns:
        if re.search(pattern, diff_or_code):
            issues.append(description)
            break

    # 2. Command Injection patterns:
    cmd_patterns = [
        (
            r"""(?i)os\.system\(\s*(?:f["']|.*(?:format|\+))""",
            "Command Injection risk: Dynamic input formatted directly into os.system().",
        ),
        (
            r"""(?i)subprocess\.(?:Popen|run|call)\(\s*(?:f["']|.*(?:\+|format))"""
            r""".*shell\s*=\s*True""",
            "Command Injection risk: Dynamic shell command executed with shell=True.",
        ),
    ]
    for pattern, description in cmd_patterns:
        if re.search(pattern, diff_or_code):
            issues.append(description)
            break

    # 3. Hardcoded Credentials / Secrets:
    secret_patterns = [
        (
            r"""(?i)(?:api_key|secret_key|private_key|auth_token)\s*=\s*"""
            r"""["'][a-zA-Z0-9_\-\.]{12,}["']""",
            "Hardcoded credential risk: Potential sensitive token or secret key found in source.",
        )
    ]
    for pattern, description in secret_patterns:
        if re.search(pattern, diff_or_code):
            issues.append(description)
            break

    # 4. Insecure Eval / Deserialization:
    unsafe_eval = [
        (
            r"""(?i)\beval\s*\([^)]*\)""",
            "Code Execution risk: Use of eval() detected, allowing arbitrary code execution.",
        ),
        (
            r"""(?i)pickle\.loads\s*\(""",
            "Insecure Deserialization risk: Use of pickle.loads() on potentially untrusted input.",
        ),
    ]
    for pattern, description in unsafe_eval:
        if re.search(pattern, diff_or_code):
            issues.append(description)
            break

    return issues


def detect_performance_issues(diff_or_code: str) -> List[str]:
    """Detect performance bottlenecks such as nested O(N^2) loops and inefficient operations."""
    issues: List[str] = []

    # 1. Nested loops leading to O(N^2) or worse complexity
    # Match outer `for ...:` followed by nested indented `for ...:`
    nested_loop_patterns = [
        (
            r"""for\s+[\w_,\s]+\s+in\s+range\([^)]+\):\s*\n"""
            r"""(?:\s*#[^\n]*\n|\s*\n)*\s+for\s+[\w_,\s]+\s+in\s+range\([^)]+\):""",
            "Algorithmic Complexity risk: Nested loops over range detected, creating O(N^2).",
        ),
        (
            r"""for\s+[\w_,\s]+\s+in\s+[\w_\.]+\s*:\s*\n"""
            r"""(?:\s*#[^\n]*\n|\s*\n)*\s+for\s+[\w_,\s]+\s+in\s+[\w_\.]+\s*:""",
            "Algorithmic Complexity risk: Nested iteration detected, potential O(N^2) bottleneck.",
        ),
    ]

    for pattern, description in nested_loop_patterns:
        if re.search(pattern, diff_or_code):
            issues.append(description)
            break

    # 2. Quadratic string concatenation inside loop:
    quadratic_str = re.search(
        r"""for\s+[\w_,\s]+\s+in\s+.*:\s*\n(?:\s*#[^\n]*\n|\s*\n)*\s+[\w_]+\s*\+=\s*[\w_]+""",
        diff_or_code,
    )
    if quadratic_str and not issues:
        issues.append(
            "Performance warning: In-place string concatenation in loop causes O(N^2) allocation."
        )

    return issues


def detect_requirement_issues(
    diff_or_code: str, requirements: Optional[List[str]] = None
) -> List[str]:
    """Detect functional requirement omissions or incomplete implementations."""
    issues: List[str] = []

    if requirements:
        for req in requirements:
            # Check for empty stub implementations
            if "TODO" in diff_or_code or "raise NotImplementedError" in diff_or_code:
                issues.append(f"Requirement incomplete: Unimplemented stub or TODO for: {req}")
                break

    return issues


def build_critic_prompt(
    role: AgentRole,
    diff_or_content: str,
    subtask: Optional[SubTask] = None,
    plan: Optional[OrchestrationPlan] = None,
) -> str:
    """Build a specialized evaluation prompt for an adversarial critic."""
    goal_str = plan.goal if plan else "Evaluate code diff against quality standards"
    task_name = subtask.name if subtask else "Coder Output"
    task_id = subtask.id if subtask else "task_coder"

    lines = [
        f"# Role: Adversarial Critic ({role.value.upper()})",
        f"Goal: {goal_str}",
        f"Target SubTask: {task_name} (ID: {task_id})",
        "",
        "## Code Diff / Implementation Under Review:",
        "```python",
        diff_or_content,
        "```",
        "",
    ]

    if role == AgentRole.SECURITY_REVIEWER:
        lines.extend(
            [
                "## Critic Instructions (SECURITY):",
                "1. Scrutinize code strictly for security vulnerabilities:",
                "   - SQL injection (e.g., f-strings or raw formatting inside SQL statements)",
                "   - Shell / command injection (e.g., os.system, subprocess with shell=True)",
                "   - Insecure deserialization or unsafe eval/exec",
                "   - Hardcoded secrets or sensitive credentials",
                "2. If vulnerabilities are found, output: STATUS: REJECTED",
                "3. If no security issues are found, output: STATUS: APPROVED",
            ]
        )
    elif role == AgentRole.PERFORMANCE_REVIEWER:
        lines.extend(
            [
                "## Critic Instructions (PERFORMANCE):",
                "1. Scrutinize code strictly for algorithmic and resource bottlenecks:",
                "   - Algorithmic complexity issues (e.g., O(N^2) nested loops over collections)",
                "   - Unnecessary repeated calculations or quadratic allocations",
                "   - Memory leaks or blocking I/O",
                "2. If performance bottlenecks are found, output: STATUS: REJECTED",
                "3. If no performance bottlenecks are found, output: STATUS: APPROVED",
            ]
        )
    elif role == AgentRole.REQUIREMENT_REVIEWER:
        lines.extend(
            [
                "## Critic Instructions (REQUIREMENTS):",
                "1. Scrutinize code against task instructions and acceptance criteria:",
                "   - Ensure requested functionality is implemented without stubbed methods.",
                "   - Ensure adherence to function signatures and type contracts.",
                "2. If requirements are missing or broken, output: STATUS: REJECTED",
                "3. If all requirements are satisfied, output: STATUS: APPROVED",
            ]
        )
    else:
        lines.extend(
            [
                "## Critic Instructions (GENERAL REVIEW):",
                "Review code quality, PEP 8 standards, and correctness.",
                "Output STATUS: APPROVED or STATUS: REJECTED.",
            ]
        )

    if subtask and subtask.spec:
        spec = subtask.spec
        lines.extend(["", "## Sub-Specification Criteria:"])
        for tc in spec.test_cases:
            lines.append(f"- Test Case [{tc.id}]: {tc.description}")
        for ac in spec.acceptance_criteria:
            lines.append(f"- Acceptance Criterion: {ac}")

    return "\n".join(lines)


def parse_critic_feedback(
    role: AgentRole,
    critic_name: str,
    run_result: Optional[RunResult] = None,
    diff_or_content: str = "",
    requirements: Optional[List[str]] = None,
) -> CriticFeedback:
    """Parse raw execution result and static analysis into a structured CriticFeedback."""
    output_text = run_result.output_text if run_result else ""
    detected_issues: List[str] = []

    # 1. Static / heuristic detection
    if role == AgentRole.SECURITY_REVIEWER:
        detected_issues.extend(detect_security_issues(diff_or_content))
    elif role == AgentRole.PERFORMANCE_REVIEWER:
        detected_issues.extend(detect_performance_issues(diff_or_content))
    elif role == AgentRole.REQUIREMENT_REVIEWER:
        detected_issues.extend(detect_requirement_issues(diff_or_content, requirements))

    # 2. Extract findings from LLM output if present
    lower_out = output_text.lower()
    if role == AgentRole.SECURITY_REVIEWER:
        has_sqli = any("sql injection" in i.lower() for i in detected_issues)
        if "sql injection" in lower_out and not has_sqli:
            detected_issues.append("Security Vulnerability: SQL Injection detected by reviewer.")
        has_cmdi = any("command injection" in i.lower() for i in detected_issues)
        if "command injection" in lower_out and not has_cmdi:
            detected_issues.append("Security Vulnerability: Command Injection detected.")
    elif role == AgentRole.PERFORMANCE_REVIEWER:
        has_loop = any("o(n^2)" in i.lower() or "nested loop" in i.lower() for i in detected_issues)
        if ("o(n^2)" in lower_out or "nested loop" in lower_out) and not has_loop:
            detected_issues.append("Performance Bottleneck: O(N^2) complexity detected.")

    # Determine approval status
    has_rejected_status = "status: rejected" in lower_out or "status: fail" in lower_out
    has_issues = len(detected_issues) > 0
    approved = (not has_rejected_status) and (not has_issues)

    # Generate feedback narrative
    if approved:
        feedback_str = f"[{role.value.upper()}] All checks passed. No issues identified."
    else:
        feedback_str = f"[{role.value.upper()}] Issues identified:\n" + "\n".join(
            f"- {issue}" for issue in detected_issues
        )
        if output_text:
            feedback_str += f"\n\nReviewer Details:\n{output_text.strip()}"

    return CriticFeedback(
        role=role,
        critic_name=critic_name,
        approved=approved,
        issues=detected_issues,
        feedback=feedback_str,
        run_result=run_result,
    )


def aggregate_critic_feedback(feedbacks: Dict[str, CriticFeedback]) -> AggregatedCriticReview:
    """Aggregate individual critic feedbacks into a unified review report."""
    all_approved = all(cf.approved for cf in feedbacks.values())

    status_label = "APPROVED ✓" if all_approved else "REJECTED ✗ (Remediation Required)"
    summary_lines = [
        "## Adversarial Critic Review Report",
        f"**Overall Status:** {status_label}",
        "",
    ]

    for role_name, cf in feedbacks.items():
        status_icon = "✓ PASSED" if cf.approved else "✗ FAILED"
        summary_lines.append(
            f"### Critic: {cf.critic_name} ({cf.role.value.upper()}) [{status_icon}]"
        )
        if cf.issues:
            summary_lines.append("**Issues Detected:**")
            for issue in cf.issues:
                summary_lines.append(f"- {issue}")
        else:
            summary_lines.append("No critical defects found.")
        summary_lines.append("")

    return AggregatedCriticReview(
        approved=all_approved,
        critics_feedback=feedbacks,
        summary="\n".join(summary_lines).strip(),
    )


async def dispatch_parallel_critics(
    runner: AgyRunner,
    diff_or_content: str,
    subtask: Optional[SubTask] = None,
    plan: Optional[OrchestrationPlan] = None,
    workers: Optional[Dict[str, WorkerAgentConfig]] = None,
    base_config: Optional[AgyConfig] = None,
) -> AggregatedCriticReview:
    """Dispatch code diff to Security, Performance, and Requirement critics in parallel."""
    target_roles = [
        AgentRole.SECURITY_REVIEWER,
        AgentRole.PERFORMANCE_REVIEWER,
        AgentRole.REQUIREMENT_REVIEWER,
    ]

    workers = workers or {}
    base_config = base_config or AgyConfig()

    async def _run_single_critic(role: AgentRole) -> tuple[str, CriticFeedback]:
        worker_cfg = workers.get(role.value) or WorkerAgentConfig(
            role=role, name=f"{role.value.replace('_', '-')}-agent"
        )
        prompt = build_critic_prompt(
            role=role, diff_or_content=diff_or_content, subtask=subtask, plan=plan
        )

        task_def = Task(
            id=f"critic_{role.value}_{subtask.id if subtask else 'task'}",
            name=f"{worker_cfg.name} Evaluation",
            prompt=prompt,
            workspace_dir=subtask.workspace_dir if subtask else None,
            timeout_seconds=60,
        )

        # Merge runner config with worker specifics
        cfg = base_config.model_copy()
        if worker_cfg.model:
            cfg.model = worker_cfg.model
        if worker_cfg.effort:
            cfg.effort = worker_cfg.effort

        critic_runner = AgyRunner(config=cfg)
        run_res = await critic_runner.execute_task(task_def)

        criteria = subtask.spec.acceptance_criteria if (subtask and subtask.spec) else None
        feedback = parse_critic_feedback(
            role=role,
            critic_name=worker_cfg.name,
            run_result=run_res,
            diff_or_content=diff_or_content,
            requirements=criteria,
        )
        return role.value, feedback

    # Execute all 3 critics concurrently
    results = await asyncio.gather(*[_run_single_critic(r) for r in target_roles])
    feedbacks_dict = dict(results)

    return aggregate_critic_feedback(feedbacks_dict)
