"""Unit and integration tests for Adversarial Critics architecture."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from harness_agent.critics import aggregate_critic_feedback
from harness_agent.models import AgentRole, OrchestrationPlan, RunResult, SubTask
from harness_agent.orchestrator import AgentOrchestrator


def test_critic_roles_enum_and_defaults():
    """Verify that all 3 adversarial critic roles are defined and normalized."""
    assert AgentRole.SECURITY_REVIEWER == "security_reviewer"
    assert AgentRole.PERFORMANCE_REVIEWER == "performance_reviewer"
    assert AgentRole.REQUIREMENT_REVIEWER == "requirement_reviewer"

    # Hyphenated aliases resolve cleanly
    assert AgentRole("security-reviewer") == AgentRole.SECURITY_REVIEWER
    assert AgentRole("performance-reviewer") == AgentRole.PERFORMANCE_REVIEWER
    assert AgentRole("requirement-reviewer") == AgentRole.REQUIREMENT_REVIEWER

    orchestrator = AgentOrchestrator()
    assert AgentRole.SECURITY_REVIEWER in orchestrator.DEFAULT_WORKERS
    assert AgentRole.PERFORMANCE_REVIEWER in orchestrator.DEFAULT_WORKERS
    assert AgentRole.REQUIREMENT_REVIEWER in orchestrator.DEFAULT_WORKERS

    sec_worker = orchestrator.DEFAULT_WORKERS[AgentRole.SECURITY_REVIEWER]
    assert sec_worker.name == "security-reviewer-agent"
    assert "security vulnerabilities" in sec_worker.system_prompt.lower()

    perf_worker = orchestrator.DEFAULT_WORKERS[AgentRole.PERFORMANCE_REVIEWER]
    assert perf_worker.name == "performance-reviewer-agent"
    assert "performance bottlenecks" in perf_worker.system_prompt.lower()

    req_worker = orchestrator.DEFAULT_WORKERS[AgentRole.REQUIREMENT_REVIEWER]
    assert req_worker.name == "requirement-reviewer-agent"
    assert "task requirements" in req_worker.system_prompt.lower()


@pytest.mark.asyncio
async def test_adversarial_critics_catches_sql_injection_and_nested_loop(monkeypatch):
    """Test Case required by Sub-Spec:

    Provide a diff with an SQL injection and a O(N^2) loop.
    Verify that the Security critic catches the injection and Perf critic catches the loop.
    """
    diff_with_issues = """
def get_user_by_query(cursor, user_input):
    query = f"SELECT * FROM users WHERE username = '{user_input}'"
    return cursor.execute(query).fetchall()

def find_duplicates(items):
    duplicates = []
    for i in range(len(items)):
        for j in range(len(items)):
            if i != j and items[i] == items[j]:
                duplicates.append(items[i])
    return duplicates
"""

    # Mock runner to simulate agent execution without real network / LLM
    mock_runner = AsyncMock()
    mock_runner.execute_task.side_effect = [
        RunResult(
            task_id="sec",
            success=True,
            exit_code=0,
            duration_seconds=0.1,
            output_text="STATUS: REJECTED\nSQL Injection vulnerability in query.",
        ),
        RunResult(
            task_id="perf",
            success=True,
            exit_code=0,
            duration_seconds=0.1,
            output_text="STATUS: REJECTED\nO(N^2) nested loop detected in duplicates.",
        ),
        RunResult(
            task_id="req",
            success=True,
            exit_code=0,
            duration_seconds=0.1,
            output_text="STATUS: APPROVED\nAll functions implemented.",
        ),
    ]

    monkeypatch.setattr("harness_agent.critics.AgyRunner.execute_task", mock_runner.execute_task)

    orchestrator = AgentOrchestrator()
    review = await orchestrator.dispatch_adversarial_critics(diff_or_content=diff_with_issues)

    # 1. Overall review must be REJECTED
    assert review.approved is False

    # 2. Security critic catches SQL injection
    assert review.security_critic is not None
    assert review.security_critic.approved is False
    assert any("sql injection" in issue.lower() for issue in review.security_critic.issues)

    # 3. Performance critic catches O(N^2) loop
    assert review.performance_critic is not None
    assert review.performance_critic.approved is False
    assert any(
        "o(n^2)" in issue.lower() or "nested loop" in issue.lower()
        for issue in review.performance_critic.issues
    )

    # 4. Requirement critic passed
    assert review.requirement_critic is not None
    assert review.requirement_critic.approved is True

    # 5. Summary aggregates findings
    assert "REJECTED" in review.summary
    assert "SQL Injection" in review.summary
    assert "O(N^2)" in review.summary or "Nested loop" in review.summary


@pytest.mark.asyncio
async def test_adversarial_critics_clean_diff_passes(monkeypatch):
    """Verify clean, secure, and performant code passes all critics."""
    clean_diff = """
def get_user_by_query(cursor, user_input):
    query = "SELECT * FROM users WHERE username = ?"
    return cursor.execute(query, (user_input,)).fetchall()

def find_duplicates(items):
    seen = set()
    duplicates = set()
    for item in items:
        if item in seen:
            duplicates.add(item)
        seen.add(item)
    return list(duplicates)
"""

    mock_runner = AsyncMock()
    mock_runner.execute_task.return_value = RunResult(
        task_id="critic",
        success=True,
        exit_code=0,
        duration_seconds=0.05,
        output_text="STATUS: APPROVED\nCode looks great.",
    )

    monkeypatch.setattr("harness_agent.critics.AgyRunner.execute_task", mock_runner.execute_task)

    orchestrator = AgentOrchestrator()
    review = await orchestrator.dispatch_adversarial_critics(diff_or_content=clean_diff)

    assert review.approved is True
    assert review.security_critic.approved is True
    assert review.performance_critic.approved is True
    assert review.requirement_critic.approved is True
    assert len(review.security_critic.issues) == 0
    assert len(review.performance_critic.issues) == 0
    assert "APPROVED" in review.summary


@pytest.mark.asyncio
async def test_parallel_dispatch_runs_concurrently(monkeypatch):
    """Verify that all 3 critics run concurrently via asyncio.gather."""
    sleep_delay = 0.08
    executed_roles = []

    async def fake_execute(self, task):
        executed_roles.append(task.id)
        await asyncio.sleep(sleep_delay)
        return RunResult(
            task_id=task.id,
            success=True,
            exit_code=0,
            duration_seconds=sleep_delay,
            output_text="STATUS: APPROVED",
        )

    monkeypatch.setattr("harness_agent.critics.AgyRunner.execute_task", fake_execute)

    orchestrator = AgentOrchestrator()
    start_time = time.time()
    review = await orchestrator.dispatch_adversarial_critics("def foo(): pass")
    duration = time.time() - start_time

    assert review.approved is True
    assert len(executed_roles) == 3
    # If run in sequence, it would take ~0.24s+. Parallel should take under 0.20s.
    assert duration < (sleep_delay * 2.8)


def test_create_patch_task_for_coder_or_patcher():
    """Verify creation of remediation task with aggregated critic feedback."""
    coder_task = SubTask(
        id="feature_api",
        name="Build API Endpoint",
        role=AgentRole.CODER,
        instruction="Implement API endpoint",
        workspace_dir="/tmp/repo",
    )

    from harness_agent.models import CriticFeedback

    feedbacks = {
        "security_reviewer": CriticFeedback(
            role=AgentRole.SECURITY_REVIEWER,
            critic_name="security-reviewer-agent",
            approved=False,
            issues=["SQL Injection in endpoint param"],
        ),
        "performance_reviewer": CriticFeedback(
            role=AgentRole.PERFORMANCE_REVIEWER,
            critic_name="performance-reviewer-agent",
            approved=False,
            issues=["O(N^2) complexity in serialization"],
        ),
    }

    review = aggregate_critic_feedback(feedbacks)
    orchestrator = AgentOrchestrator()

    patch_task = orchestrator.create_patch_task(coder_task, review)

    assert patch_task.id == "feature_api_patch"
    assert patch_task.role == AgentRole.CODER
    assert "feature_api" in patch_task.depends_on
    assert "SQL Injection in endpoint param" in patch_task.instruction
    assert "O(N^2) complexity in serialization" in patch_task.instruction
    assert patch_task.workspace_dir == "/tmp/repo"


@pytest.mark.asyncio
async def test_run_plan_automatically_triggers_adversarial_critics(monkeypatch):
    """Verify that completing a Coder subtask automatically triggers critics."""
    plan = OrchestrationPlan(
        plan_id="plan_critics_integration",
        goal="Develop feature with critic gate",
        tasks=[
            SubTask(
                id="coder_subtask",
                name="Implement Auth",
                role=AgentRole.CODER,
                instruction="Write auth module",
            )
        ],
        enable_adversarial_critics=True,
    )

    coder_code = """
def authenticate(cursor, user, pwd):
    query = f"SELECT * FROM users WHERE user='{user}' AND pass='{pwd}'"
    return cursor.execute(query).fetchone()
"""

    async def mock_execute(self, task):
        if "coder" in task.id:
            return RunResult(
                task_id=task.id,
                success=True,
                exit_code=0,
                duration_seconds=0.2,
                output_text=coder_code,
            )
        # Critic tasks
        return RunResult(
            task_id=task.id,
            success=True,
            exit_code=0,
            duration_seconds=0.05,
            output_text="STATUS: REJECTED\nSecurity issue found.",
        )

    monkeypatch.setattr("harness_agent.orchestrator.AgyRunner.execute_task", mock_execute)
    monkeypatch.setattr("harness_agent.critics.AgyRunner.execute_task", mock_execute)

    orchestrator = AgentOrchestrator()
    result = await orchestrator.run_plan(plan)

    assert result.success is True  # Coder subtask completed
    assert "coder_subtask" in result.critic_reviews
    coder_review = result.critic_reviews["coder_subtask"]
    assert coder_review.approved is False
    assert any("sql injection" in issue.lower() for issue in coder_review.security_critic.issues)

    # Passed back to coder result output
    coder_res = result.task_results["coder_subtask"]
    assert coder_res.critic_review is not None
    assert "Adversarial Critic Review Report" in coder_res.output_text
