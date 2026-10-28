"""Integration tests for Role Selection Engine, FSM Transitions, and Dispatch Contract."""

from pathlib import Path
from unittest.mock import patch

from harness_agent.core.dispatch import (
    build_worker_dispatch_contract_with_role,
    filter_tools_for_role_and_state,
    transition_lifecycle_state,
)
from harness_agent.core.models import (
    STATE_TOOL_ALLOWLIST,
    AgentLifecycleState,
    AgentRole,
    ArchitectureSpec,
    DirectoryLayoutSpec,
    RoleSelectionResult,
    TechStackSpec,
)
from harness_agent.core.orchestrator import conduct_role_selection


class TestRoleSelectionLifecycle:
    """Integration test suite covering role selection, FSM transitions, and dispatch contracts."""

    def test_role_selection_interactive_prompt_mock(self, tmp_path: Path):
        """Test interactive prompt flow and confirmed skill assignment."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test-pkg"\ndependencies = ["fastapi>=0.100.0"]\n',
            encoding="utf-8",
        )

        with patch("builtins.input", return_value="sdlc-test-driven-development, custom-skill"):
            with patch("os.isatty", return_value=True):
                result = conduct_role_selection(
                    repo_root=tmp_path,
                    target_role=AgentRole.BACKEND,
                    interactive=True,
                )

        assert isinstance(result, RoleSelectionResult)
        assert result.role == AgentRole.BACKEND
        assert "sdlc-clean-code-standards" in result.confirmed_core_skills
        assert "sdlc-api-interface-design" in result.confirmed_core_skills
        assert "sdlc-test-driven-development" in result.confirmed_optional_skills
        assert "custom-skill" in result.confirmed_optional_skills

        # Verify persisted to .ai/context/role_selection.json
        persisted_file = tmp_path / ".ai" / "context" / "role_selection.json"
        assert persisted_file.is_file()
        loaded = RoleSelectionResult.model_validate_json(persisted_file.read_text(encoding="utf-8"))
        assert loaded.role == AgentRole.BACKEND
        assert "custom-skill" in loaded.confirmed_optional_skills

        # Verify auto-scaffolded skill created
        fastapi_skill = tmp_path / ".agents" / "skills" / "fastapi" / "SKILL.md"
        assert fastapi_skill.is_file()

    def test_role_selection_non_interactive_fallback(self, tmp_path: Path):
        """Test auto-approval in headless mode without hanging."""
        (tmp_path / "requirements.txt").write_text("torch>=2.0.0\npytest\n", encoding="utf-8")

        result = conduct_role_selection(
            repo_root=tmp_path,
            target_role=AgentRole.AI_ML,
            interactive=False,
            additional_skills=["sdlc-clean-code-standards"],
        )

        assert isinstance(result, RoleSelectionResult)
        assert result.role == AgentRole.AI_ML
        assert "pytorch-patterns" in result.confirmed_core_skills
        assert "sdlc-clean-code-standards" in result.confirmed_core_skills

        persisted_file = tmp_path / ".ai" / "context" / "role_selection.json"
        assert persisted_file.is_file()

        # If role_selection.json already exists, conduct_role_selection loads it
        second_result = conduct_role_selection(
            repo_root=tmp_path,
            target_role=AgentRole.FRONTEND,  # should be ignored because file exists
            interactive=False,
        )
        assert second_result.role == AgentRole.AI_ML

    def test_lifecycle_fsm_discovery_to_role_selection_to_planning(self):
        """Verify FSM state transitions pass without error."""
        # DISCOVERY -> ROLE_SELECTION
        allowed, new_state, msg = transition_lifecycle_state(
            current_state=AgentLifecycleState.DISCOVERY,
            target_state=AgentLifecycleState.ROLE_SELECTION,
        )
        assert allowed is True
        assert new_state == AgentLifecycleState.ROLE_SELECTION

        # ROLE_SELECTION -> PLANNING
        allowed, new_state, msg = transition_lifecycle_state(
            current_state=AgentLifecycleState.ROLE_SELECTION,
            target_state=AgentLifecycleState.PLANNING,
        )
        assert allowed is True
        assert new_state == AgentLifecycleState.PLANNING

        # Direct DISCOVERY -> PLANNING (backward compatibility with valid ArchitectureSpec)
        valid_spec = ArchitectureSpec(
            project_name="demo",
            description="demo",
            layout=DirectoryLayoutSpec(
                src_dir="src",
                tests_unit_dir="tests/unit",
                tests_integration_dir="tests/integration",
                docs_dir="docs",
            ),
            tech_stack=TechStackSpec(
                primary_language="python",
                language_version=">=3.10",
                frameworks=[],
            ),
            approved=True,
        )
        allowed, new_state, msg = transition_lifecycle_state(
            current_state=AgentLifecycleState.DISCOVERY,
            target_state=AgentLifecycleState.PLANNING,
            architecture_spec=valid_spec,
        )
        assert allowed is True
        assert new_state == AgentLifecycleState.PLANNING

        # ROLE_SELECTION -> FAILED
        allowed, new_state, msg = transition_lifecycle_state(
            current_state=AgentLifecycleState.ROLE_SELECTION,
            target_state=AgentLifecycleState.FAILED,
        )
        assert allowed is True
        assert new_state == AgentLifecycleState.FAILED

    def test_worker_dispatch_contract_receives_confirmed_skills(self):
        """Verify generated Herdr dispatch prompt contains confirmed core and optional skills."""
        selection = RoleSelectionResult(
            role=AgentRole.CODER,
            confirmed_core_skills=["sdlc-clean-code-standards"],
            confirmed_optional_skills=["sdlc-conventional-commit", "pytorch-patterns"],
            effective_tools=["view_file", "replace_file_content", "apply_patch"],
        )

        contract = build_worker_dispatch_contract_with_role(
            task_id="task_03_test",
            spec_path=".ai/plans/subtasks/2026-10-28/subtask_03.md",
            role_selection=selection,
            worktree_path=".worktrees/agent/task_03_test",
        )

        assert "[ROLE: Leaf Coder Worker]" in contract
        assert "Spec: .ai/plans/subtasks/2026-10-28/subtask_03.md" in contract
        expected_skills = (
            "Required Skills: sdlc-clean-code-standards, "
            "sdlc-conventional-commit, pytorch-patterns"
        )
        assert expected_skills in contract
        assert "Target Paths: .worktrees/agent/task_03_test" in contract
        expected_target = (
            "Target: 100% pytest pass -> write status .complete -> output [WORKER_COMPLETED]."
        )
        assert expected_target in contract

    def test_filter_tools_for_role_and_state_role_selection_and_execution(self):
        """Verify dynamic tool filtering in ROLE_SELECTION and EXECUTION states."""
        all_tools = [
            {"name": "view_file"},
            {"name": "read_file"},
            {"name": "replace_file_content"},
            {"name": "apply_patch"},
            {"name": "write_to_file"},
            {"name": "ask_question"},
            {"name": "run_command"},
            {"name": "manage_task"},
            {"name": "search_web"},
        ]

        # In ROLE_SELECTION, tools are restricted according to STATE_TOOL_ALLOWLIST
        filtered_rs = filter_tools_for_role_and_state(
            all_tools=all_tools,
            role=AgentRole.CODER,
            state=AgentLifecycleState.ROLE_SELECTION,
        )
        names_rs = [t["name"] for t in filtered_rs]
        for name in names_rs:
            assert name in STATE_TOOL_ALLOWLIST[AgentLifecycleState.ROLE_SELECTION]
        assert "apply_patch" not in names_rs
        assert "run_command" not in names_rs
        assert "view_file" in names_rs

        # In EXECUTION, tools are restricted to effective_tools in role_selection
        selection = RoleSelectionResult(
            role=AgentRole.CODER,
            confirmed_core_skills=["sdlc-clean-code-standards"],
            confirmed_optional_skills=[],
            effective_tools=["view_file", "replace_file_content"],  # no apply_patch
        )
        filtered_exec = filter_tools_for_role_and_state(
            all_tools=all_tools,
            role=AgentRole.CODER,
            state=AgentLifecycleState.EXECUTION,
            role_selection=selection,
        )
        names_exec = [t["name"] for t in filtered_exec]
        assert "view_file" in names_exec
        assert "replace_file_content" in names_exec
        assert "apply_patch" not in names_exec
