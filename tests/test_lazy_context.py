"""Tests for Lazy Context Loading in AgentOrchestrator.

Validates:
1. Orchestrator dispatch only passes the assigned subtask and no other subtasks.
2. Explicit reading and passing of .ai/plan/subtask_[id].md files.
3. Passing of specific interface files while ignoring the rest of the codebase.
"""

from unittest.mock import AsyncMock

import pytest

from harness_agent.models import AgentRole, OrchestrationPlan, RunResult, SubTask
from harness_agent.orchestrator import AgentOrchestrator


def test_prompt_contains_only_assigned_subtask():
    """Inspect the prompt sent to a worker agent to ensure it only contains its

    assigned subtask and no other subtasks.
    """
    plan = OrchestrationPlan(
        plan_id="plan_lazy_test",
        goal="Develop authentication and billing",
        tasks=[
            SubTask(
                id="task_auth",
                name="Authentication Engine",
                role=AgentRole.CODER,
                instruction="Implement OAuth2 JWT authentication handler.",
                description="Secret auth implementation details that should not leak.",
            ),
            SubTask(
                id="task_billing",
                name="Billing Stripe Gateway",
                role=AgentRole.CODER,
                instruction="Implement Stripe webhook and checkout session.",
                description="Confidential billing keys and payment workflow.",
                depends_on=["task_auth"],
            ),
            SubTask(
                id="task_notifications",
                name="Notification Dispatcher",
                role=AgentRole.CODER,
                instruction="Send email confirmation via SendGrid.",
                depends_on=["task_billing"],
            ),
        ],
    )

    orchestrator = AgentOrchestrator()
    subtask_billing = plan.tasks[1]
    worker = orchestrator.DEFAULT_WORKERS[AgentRole.CODER]

    prompt = orchestrator._build_worker_prompt(
        plan=plan,
        subtask=subtask_billing,
        worker=worker,
        task_results={
            "task_auth": RunResult(
                task_id="task_auth",
                success=True,
                exit_code=0,
                duration_seconds=1.0,
                output_text="auth token generated: SECRET_AUTH_OUTPUT",
            )
        },
    )

    # 1. Assigned subtask must be clearly present
    assert "Assigned SubTask: Billing Stripe Gateway" in prompt
    assert "task_billing" in prompt
    assert "Implement Stripe webhook and checkout session." in prompt
    assert "Confidential billing keys and payment workflow." in prompt

    # 2. Other subtasks must NOT be present in the prompt
    assert "task_auth" not in prompt
    assert "Authentication Engine" not in prompt
    assert "Secret auth implementation details" not in prompt
    assert "SECRET_AUTH_OUTPUT" not in prompt

    assert "task_notifications" not in prompt
    assert "Notification Dispatcher" not in prompt
    assert "SendGrid" not in prompt


def test_lazy_context_loads_subtask_plan_file(tmp_path):
    """Orchestrator explicitly reads and passes ONLY the specific .ai/plan/subtask_[id].md file."""
    # Create .ai/plan directory with subtask markdown files
    plan_dir = tmp_path / ".ai" / "plan"
    plan_dir.mkdir(parents=True)

    plan_subtask_1 = plan_dir / "subtask_1_feature_a.md"
    plan_subtask_1.write_text(
        "# Subtask 1: Feature A Specification\n\nDetailed requirements for Feature A only.",
        encoding="utf-8",
    )

    plan_subtask_2 = plan_dir / "subtask_2_feature_b.md"
    plan_subtask_2.write_text(
        "# Subtask 2: Feature B Specification\n\nDetailed requirements for Feature B only.",
        encoding="utf-8",
    )

    plan = OrchestrationPlan(
        plan_id="plan_files_test",
        goal="Build two features",
        tasks=[
            SubTask(
                id="1",
                name="Feature A",
                role=AgentRole.CODER,
                instruction="Implement Feature A",
            ),
            SubTask(
                id="2",
                name="Feature B",
                role=AgentRole.CODER,
                instruction="Implement Feature B",
            ),
        ],
    )

    orchestrator = AgentOrchestrator()
    worker = orchestrator.DEFAULT_WORKERS[AgentRole.CODER]

    # Prompt for Task 1
    prompt_1 = orchestrator._build_worker_prompt(
        plan=plan,
        subtask=plan.tasks[0],
        worker=worker,
        workspace_dir=str(tmp_path),
    )
    assert "Detailed requirements for Feature A only." in prompt_1
    assert "Detailed requirements for Feature B only." not in prompt_1

    # Prompt for Task 2
    prompt_2 = orchestrator._build_worker_prompt(
        plan=plan,
        subtask=plan.tasks[1],
        worker=worker,
        workspace_dir=str(tmp_path),
    )
    assert "Detailed requirements for Feature B only." in prompt_2
    assert "Detailed requirements for Feature A only." not in prompt_2


def test_lazy_context_passes_specific_interface_files(tmp_path):
    """Pass specific interface files (e.g. schema Pydantic files),
    ignoring the rest of the codebase.
    """
    # Create interface files and unrelated codebase files
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)

    schema_file = src_dir / "schemas.py"
    schema_file.write_text(
        "class UserModel(BaseModel):\n    user_id: str\n    email: str\n",
        encoding="utf-8",
    )

    unrelated_file = src_dir / "internal_database_driver.py"
    unrelated_file.write_text(
        "class PrivateDBPool:\n    def execute_raw_sql(self):\n        pass\n",
        encoding="utf-8",
    )

    subtask = SubTask(
        id="user_service",
        name="User Service",
        role=AgentRole.CODER,
        instruction="Implement user registration service",
        interface_files=["src/schemas.py"],
    )

    plan = OrchestrationPlan(
        plan_id="plan_interface_test",
        goal="User service",
        tasks=[subtask],
    )

    orchestrator = AgentOrchestrator()
    worker = orchestrator.DEFAULT_WORKERS[AgentRole.CODER]

    prompt = orchestrator._build_worker_prompt(
        plan=plan,
        subtask=subtask,
        worker=worker,
        workspace_dir=str(tmp_path),
    )

    # Relevant interface is present
    assert "Relevant Interface Specifications:" in prompt
    assert "class UserModel(BaseModel):" in prompt
    assert "user_id: str" in prompt

    # Unrelated codebase files are completely ignored
    assert "PrivateDBPool" not in prompt
    assert "execute_raw_sql" not in prompt


@pytest.mark.asyncio
async def test_dispatch_subtask_executes_with_lazy_context(tmp_path, monkeypatch):
    """Verify that dispatch_subtask / dispatch passes only lazy context
    to the worker task runner.
    """
    plan_dir = tmp_path / ".ai" / "plan"
    plan_dir.mkdir(parents=True)
    (plan_dir / "subtask_auth.md").write_text("# Subtask Auth Markdown Plan", encoding="utf-8")

    subtask = SubTask(
        id="auth",
        name="Auth Module",
        role=AgentRole.CODER,
        instruction="Build auth",
        interface_contents={
            "interfaces/auth_proto.py": "def verify_token(token: str) -> bool: ..."
        },
    )

    plan = OrchestrationPlan(
        plan_id="plan_dispatch_test",
        goal="Secure API",
        tasks=[
            subtask,
            SubTask(
                id="payments",
                name="Payment Module",
                role=AgentRole.CODER,
                instruction="Process payments",
            ),
        ],
    )

    mock_runner = AsyncMock()
    mock_runner.execute_task.return_value = RunResult(
        task_id="auth",
        success=True,
        exit_code=0,
        duration_seconds=0.5,
    )
    monkeypatch.setattr(
        "harness_agent.orchestrator.AgyRunner.execute_task", mock_runner.execute_task
    )

    orchestrator = AgentOrchestrator()
    # Test dispatch alias
    result = await orchestrator.dispatch(plan, subtask, workspace_dir=str(tmp_path))

    assert result.success is True
    assert mock_runner.execute_task.called
    dispatched_task = mock_runner.execute_task.call_args[0][0]

    # Verify dispatched task prompt
    assert "Assigned SubTask: Auth Module" in dispatched_task.prompt
    assert "# Subtask Auth Markdown Plan" in dispatched_task.prompt
    assert "def verify_token(token: str) -> bool: ..." in dispatched_task.prompt

    # Ensure other subtask is not leaked
    assert "payments" not in dispatched_task.prompt
    assert "Payment Module" not in dispatched_task.prompt
    assert "Process payments" not in dispatched_task.prompt


def test_real_repo_subtask_plan_resolution():
    """Verify that orchestrator resolves actual repository .ai/plan/subtask_3_lazy_context.md."""
    orchestrator = AgentOrchestrator()
    subtask = SubTask(
        id="3",
        name="Lazy Context Loading",
        role=AgentRole.CODER,
        instruction="Implement lazy context loading",
    )

    resolved = orchestrator.resolve_subtask_plan_file(subtask)
    assert resolved is not None
    assert "subtask_3_lazy_context.md" in resolved

    content = orchestrator.read_subtask_plan(subtask)
    assert content is not None
    assert "# Sub-Spec: Lazy Context Loading" in content
    assert "Prevent context rot" in content


def test_real_repo_agents_rule_resolution():
    """Verify that orchestrator resolves and reads AGENTS.md in the repository root."""
    orchestrator = AgentOrchestrator()
    resolved = orchestrator.resolve_agents_rule_file()
    assert resolved is not None
    assert resolved.endswith("AGENTS.md")

    content = orchestrator.read_agents_rules()
    assert content is not None
    assert "Central Orchestrator Pattern" in content
    assert "Conda Environment" in content


def test_worker_prompt_enforces_agents_md_guidelines():
    """Verify that worker prompts always inject AGENTS.md system standards."""
    orchestrator = AgentOrchestrator()
    subtask = SubTask(
        id="task_audit",
        name="Security Audit",
        role=AgentRole.CODER,
        instruction="Audit code diff",
    )
    plan = OrchestrationPlan(
        plan_id="plan_audit",
        goal="Audit codebase",
        tasks=[subtask],
    )
    worker = orchestrator.DEFAULT_WORKERS[AgentRole.CODER]
    prompt = orchestrator._build_worker_prompt(
        plan=plan,
        subtask=subtask,
        worker=worker,
    )

    assert "## Mandatory System Guidelines & Rules (AGENTS.md):" in prompt
    assert "**MANDATORY FIRST STEP:** Read `AGENTS.md`" in prompt
    assert "conda run -n pytorch" in prompt
    assert "Black (100 line length)" in prompt
    assert "PATCH, NEVER REGENERATE" in prompt
    assert "branch protection" in prompt
