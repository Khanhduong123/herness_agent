"""Unit tests for RoleContract models, registry, and FSM state."""

import time

from harness_agent.core.models import (
    ROLE_DEFAULT_SKILLS,
    ROLE_REGISTRY,
    ROLE_TOOL_ALLOWLIST,
    STATE_TOOL_ALLOWLIST,
    AgentLifecycleState,
    AgentRole,
    RoleContract,
    RoleSelectionResult,
)


def test_role_contract_instantiation():
    """Validate RoleContract fields and default values."""
    contract = RoleContract(
        role=AgentRole.CODER,
        description="Coder worker role",
        core_skills=["sdlc-clean-code-standards"],
        optional_skills=["sdlc-conventional-commit"],
        tool_allowlist=["view_file", "apply_patch"],
    )
    assert contract.role == AgentRole.CODER
    assert contract.description == "Coder worker role"
    assert contract.core_skills == ["sdlc-clean-code-standards"]
    assert contract.optional_skills == ["sdlc-conventional-commit"]
    assert contract.tool_allowlist == ["view_file", "apply_patch"]
    assert contract.default_model is None
    assert contract.default_effort == "low"


def test_role_contract_empty_optional_skills():
    """Test empty optional skills default handling without errors."""
    contract = RoleContract(
        role=AgentRole.REVIEWER,
        description="Reviewer role",
    )
    assert contract.optional_skills == []
    assert contract.core_skills == []
    assert contract.tool_allowlist == []


def test_role_selection_result():
    """Validate RoleSelectionResult schema and defaults."""
    before = time.time()
    result = RoleSelectionResult(
        role=AgentRole.BACKEND,
        confirmed_core_skills=["sdlc-api-interface-design"],
        confirmed_optional_skills=["sdlc-test-driven-development"],
        effective_tools=["view_file", "run_command"],
    )
    assert result.role == AgentRole.BACKEND
    assert result.confirmed_core_skills == ["sdlc-api-interface-design"]
    assert result.confirmed_optional_skills == ["sdlc-test-driven-development"]
    assert result.effective_tools == ["view_file", "run_command"]
    assert result.timestamp >= before


def test_role_registry_integrity():
    """Assert all AgentRole members have a corresponding RoleContract in ROLE_REGISTRY."""
    for role in AgentRole:
        assert role in ROLE_REGISTRY, f"Role {role} missing from ROLE_REGISTRY"
        contract = ROLE_REGISTRY[role]
        assert isinstance(contract, RoleContract)
        assert contract.role == role
        assert isinstance(contract.description, str) and len(contract.description) > 0
        assert isinstance(contract.tool_allowlist, list) and len(contract.tool_allowlist) > 0


def test_backward_compatible_allowlists():
    """Ensure ROLE_TOOL_ALLOWLIST and ROLE_DEFAULT_SKILLS match ROLE_REGISTRY."""
    for role, contract in ROLE_REGISTRY.items():
        assert role in ROLE_TOOL_ALLOWLIST
        assert ROLE_TOOL_ALLOWLIST[role] == contract.tool_allowlist

        if contract.core_skills:
            assert role in ROLE_DEFAULT_SKILLS
            assert ROLE_DEFAULT_SKILLS[role] == contract.core_skills


def test_fsm_role_selection_state():
    """Assert AgentLifecycleState.ROLE_SELECTION exists and has allowed tools."""
    assert AgentLifecycleState.ROLE_SELECTION == "role_selection"
    assert AgentLifecycleState.ROLE_SELECTION in STATE_TOOL_ALLOWLIST
    tools = STATE_TOOL_ALLOWLIST[AgentLifecycleState.ROLE_SELECTION]
    assert "view_file" in tools
    assert "read_file" in tools
    assert "ask_question" in tools
    assert "write_to_file" in tools
    assert "write_file" in tools


def test_agent_role_missing_normalization():
    """Validate legacy string parsing and hyphen conversion for AgentRole."""
    assert AgentRole("backend-engineer") is None or AgentRole("ai-ml") == AgentRole.AI_ML
    assert AgentRole("SECURITY-REVIEWER") == AgentRole.SECURITY_REVIEWER
    assert AgentRole("coder") == AgentRole.CODER
