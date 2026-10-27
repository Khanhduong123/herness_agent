"""Comprehensive unit tests for dynamic tool gating FSM and hooks."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

from harness_agent.core.dispatch import (
    filter_tools_for_role_and_state,
    is_approval_command,
    transition_lifecycle_state,
)
from harness_agent.core.models import AgentLifecycleState, AgentRole


@pytest.fixture
def standard_toolset() -> List[Dict[str, Any]]:
    """Standard toolset representing development and orchestrator capabilities."""
    return [
        {"name": "view_file", "description": "Read file contents"},
        {"name": "read_file", "description": "Read file contents (alias)"},
        {"name": "replace_file_content", "description": "Modify file block"},
        {"name": "write_to_file", "description": "Create or write file"},
        {"name": "write_file", "description": "Write file (alias)"},
        {"name": "apply_patch", "description": "Apply git unified patch"},
        {"name": "multi_replace_file_content", "description": "Multiple replacements"},
        {"name": "run_command", "description": "Execute shell command"},
        {"name": "manage_task", "description": "Manage background tasks"},
        {"name": "ask_question", "description": "Prompt user question"},
        {"name": "search_web", "description": "Search internet"},
        {"name": "read_url_content", "description": "Fetch remote url"},
        {"name": "schedule", "description": "Schedule timers"},
        {"name": "send_message", "description": "Send inter-agent message"},
        {"name": "invoke_subagent", "description": "Launch hidden subagent"},
        {"name": "define_subagent", "description": "Define custom subagent"},
        {"name": "create_pull_request", "description": "Create github PR"},
        {"name": "git_merge", "description": "Direct git merge"},
    ]


class TestLifecycleStateTransitions:
    """Test Case 1: Lifecycle State Transitions & Human Gate enforcement."""

    def test_transition_planning_to_plan_review(self):
        """Verify transition from PLANNING to PLAN_REVIEW is valid."""
        allowed, new_state, msg = transition_lifecycle_state(
            current_state=AgentLifecycleState.PLANNING,
            target_state=AgentLifecycleState.PLAN_REVIEW,
        )
        assert allowed is True
        assert new_state == AgentLifecycleState.PLAN_REVIEW
        assert "plan_review" in msg

    def test_transition_plan_review_to_execution_fails_without_approval(self):
        """Verify transition fails when approval is missing and input is regular chat."""
        chat_inputs = [
            "looks cool",
            "can you start?",
            "go ahead and do it please",
            "let's proceed now",  # not an exact approval token
            "lgtm",
            "",
            None,
        ]
        for user_msg in chat_inputs:
            allowed, state, reason = transition_lifecycle_state(
                current_state=AgentLifecycleState.PLAN_REVIEW,
                target_state=AgentLifecycleState.EXECUTION,
                user_input=user_msg,
                explicit_approval=False,
            )
            assert allowed is False, f"Expected blocked transition for input: {user_msg}"
            assert state == AgentLifecycleState.PLAN_REVIEW
            assert "Explicit user approval required" in reason

    def test_transition_plan_review_to_execution_succeeds_with_explicit_approval_flag(self):
        """Verify transition from PLAN_REVIEW to EXECUTION succeeds when explicit_approval=True."""
        allowed, new_state, msg = transition_lifecycle_state(
            current_state=AgentLifecycleState.PLAN_REVIEW,
            target_state=AgentLifecycleState.EXECUTION,
            user_input=None,
            explicit_approval=True,
        )
        assert allowed is True
        assert new_state == AgentLifecycleState.EXECUTION
        assert "approved" in msg.lower()

    def test_transition_plan_review_to_execution_succeeds_with_approval_tokens(self):
        """Verify transition succeeds when user_input contains recognized approval tokens."""
        approval_tokens = ["/approve", "approve", "approved", "/proceed", "proceed", "yes"]
        for token in approval_tokens:
            allowed, new_state, msg = transition_lifecycle_state(
                current_state=AgentLifecycleState.PLAN_REVIEW,
                target_state=AgentLifecycleState.EXECUTION,
                user_input=token,
                explicit_approval=False,
            )
            assert allowed is True, f"Failed transition for approval token: {token}"
            assert new_state == AgentLifecycleState.EXECUTION

    def test_invalid_state_transitions_are_rejected(self):
        """Verify invalid state jumps are rejected."""
        # PLANNING cannot jump directly to EXECUTION, VALIDATING, CRITIC_GATE, or COMPLETED
        for target in [
            AgentLifecycleState.EXECUTION,
            AgentLifecycleState.VALIDATING,
            AgentLifecycleState.CRITIC_GATE,
            AgentLifecycleState.COMPLETED,
        ]:
            allowed, state, reason = transition_lifecycle_state(
                current_state=AgentLifecycleState.PLANNING,
                target_state=target,
            )
            assert allowed is False
            assert state == AgentLifecycleState.PLANNING
            assert "Invalid state transition" in reason

        # COMPLETED is terminal (no outgoing transitions)
        for target in [AgentLifecycleState.PLANNING, AgentLifecycleState.EXECUTION]:
            allowed, state, reason = transition_lifecycle_state(
                current_state=AgentLifecycleState.COMPLETED,
                target_state=target,
            )
            assert allowed is False
            assert state == AgentLifecycleState.COMPLETED

    def test_is_approval_command_helper(self):
        """Unit test for is_approval_command helper function."""
        assert is_approval_command("/approve") is True
        assert is_approval_command("  /APPROVE  ") is True
        assert is_approval_command("proceed") is True
        assert is_approval_command("yes") is True
        assert is_approval_command("no") is False
        assert is_approval_command("looks good") is False
        assert is_approval_command("") is False


class TestRoleAndStateToolAllowlistIntersection:
    """Test Case 2: Role and State Tool Allowlist Intersection."""

    def test_coder_in_plan_review_is_read_only(self, standard_toolset):
        """Verify Coder in PLAN_REVIEW has modification tools filtered out."""
        filtered = filter_tools_for_role_and_state(
            all_tools=standard_toolset,
            role=AgentRole.CODER,
            state=AgentLifecycleState.PLAN_REVIEW,
        )
        tool_names = {t["name"] for t in filtered}

        # Mutation tools must be completely stripped
        assert "replace_file_content" not in tool_names
        assert "apply_patch" not in tool_names
        assert "write_to_file" not in tool_names
        assert "write_file" not in tool_names
        assert "multi_replace_file_content" not in tool_names
        assert "run_command" not in tool_names

        # Read-only tools preserved
        assert "view_file" in tool_names

    def test_coder_in_execution_has_mutation_tools(self, standard_toolset):
        """Verify Coder in EXECUTION state has access to all coder modification tools."""
        filtered = filter_tools_for_role_and_state(
            all_tools=standard_toolset,
            role=AgentRole.CODER,
            state=AgentLifecycleState.EXECUTION,
        )
        tool_names = {t["name"] for t in filtered}

        assert "view_file" in tool_names
        assert "replace_file_content" in tool_names
        assert "write_to_file" in tool_names
        assert "apply_patch" in tool_names
        assert "multi_replace_file_content" in tool_names
        assert "run_command" in tool_names

        # Subagent and direct git tools remain forbidden
        assert "invoke_subagent" not in tool_names
        assert "git_merge" not in tool_names
        assert "create_pull_request" not in tool_names

    def test_orchestrator_in_planning_state(self, standard_toolset):
        """Verify Orchestrator in PLANNING contains no code patch tools and no subagents."""
        filtered = filter_tools_for_role_and_state(
            all_tools=standard_toolset,
            role=AgentRole.ORCHESTRATOR,
            state=AgentLifecycleState.PLANNING,
        )
        tool_names = {t["name"] for t in filtered}

        # No code patch tools
        assert "apply_patch" not in tool_names
        assert "replace_file_content" not in tool_names
        assert "multi_replace_file_content" not in tool_names

        # No hidden subagent tools (Rule 0)
        assert "invoke_subagent" not in tool_names
        assert "define_subagent" not in tool_names

        # Planning tools allowed
        assert "view_file" in tool_names
        assert "write_to_file" in tool_names  # Allowed by schema, path-gated by hook
        assert "ask_question" in tool_names

    def test_critic_reviewer_always_read_only(self, standard_toolset):
        """Verify Critic reviewers never receive modification tools."""
        for role in [
            AgentRole.REVIEWER,
            AgentRole.SECURITY_REVIEWER,
            AgentRole.PERFORMANCE_REVIEWER,
            AgentRole.REQUIREMENT_REVIEWER,
        ]:
            for state in [
                AgentLifecycleState.PLANNING,
                AgentLifecycleState.EXECUTION,
                AgentLifecycleState.CRITIC_GATE,
            ]:
                filtered = filter_tools_for_role_and_state(
                    all_tools=standard_toolset,
                    role=role,
                    state=state,
                )
                tool_names = {t["name"] for t in filtered}
                assert "replace_file_content" not in tool_names
                assert "apply_patch" not in tool_names
                assert "write_to_file" not in tool_names
                assert "run_command" not in tool_names


class TestPreToolUseHookHardDenial:
    """Test Case 3: PreToolUse Hook Hard-Denial Testing via subprocess invocation."""

    @pytest.fixture
    def hook_script(self) -> Path:
        """Path to gate_tool_execution.py hook script."""
        repo_root = Path(__file__).resolve().parent.parent.parent
        script = repo_root / ".agents" / "hooks" / "gate_tool_execution.py"
        assert script.exists(), f"Hook script not found at {script}"
        return script

    def _invoke_hook(self, hook_script: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Invoke hook script with stdin JSON payload and parse stdout JSON."""
        # Use main repo root or temp dir as cwd so is_in_worker_worktree does not trigger
        # when running tests inside an isolated agent worktree workspace (.worktrees/agent/...).
        target_cwd = (
            hook_script.parents[5]
            if len(hook_script.parents) > 5 and (hook_script.parents[5] / "src").exists()
            else hook_script.parents[2]
        )
        result = subprocess.run(
            [sys.executable, str(hook_script)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            cwd=str(target_cwd),
        )
        assert result.returncode == 0, f"Hook execution failed: {result.stderr}"
        return json.loads(result.stdout.strip())

    def test_denies_mutation_on_src_file(self, hook_script):
        """Execute hook with payload attempting write_file on src/harness_agent/cli.py -> deny."""
        payload = {
            "toolCall": {
                "name": "write_file",
                "args": {"Path": "src/harness_agent/cli.py"},
            }
        }
        res = self._invoke_hook(hook_script, payload)
        assert res.get("decision") == "deny"
        assert "RULE 0 HARD-GATE" in res.get("reason", "")

    def test_denies_mutation_on_tests_file(self, hook_script):
        """Execute hook with replace_file_content on tests/unit/test_cli.py -> deny."""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {"target_file": "tests/unit/test_cli.py"},
            }
        }
        res = self._invoke_hook(hook_script, payload)
        assert res.get("decision") == "deny"
        assert "RULE 0 HARD-GATE" in res.get("reason", "")

    def test_allows_write_on_plan_files(self, hook_script):
        """Execute hook with payload attempting write_file on .ai/plans/main/test.md -> allow."""
        payload = {
            "toolCall": {
                "name": "write_file",
                "args": {"Path": ".ai/plans/main/2026-10-27/main_test.md"},
            }
        }
        res = self._invoke_hook(hook_script, payload)
        assert res.get("decision") == "allow"
        assert res.get("reason") is None

    def test_denies_invoke_subagent_tool(self, hook_script):
        """Execute hook with payload attempting invoke_subagent -> deny."""
        payload = {
            "toolCall": {
                "name": "invoke_subagent",
                "args": {"Role": "Coder"},
            }
        }
        res = self._invoke_hook(hook_script, payload)
        assert res.get("decision") == "deny"
        assert "Hidden background subagents are strictly prohibited" in res.get("reason", "")

    def test_denies_define_subagent_tool(self, hook_script):
        """Execute hook with payload attempting define_subagent -> deny."""
        payload = {
            "toolCall": {
                "name": "define_subagent",
                "args": {"Name": "custom_agent"},
            }
        }
        res = self._invoke_hook(hook_script, payload)
        assert res.get("decision") == "deny"
        assert "Hidden background subagents are strictly prohibited" in res.get("reason", "")

    def test_allows_harmless_tools(self, hook_script):
        """Execute hook with read_file tool -> allow."""
        payload = {
            "toolCall": {
                "name": "read_file",
                "args": {"Path": "src/harness_agent/cli.py"},
            }
        }
        res = self._invoke_hook(hook_script, payload)
        assert res.get("decision") == "allow"
