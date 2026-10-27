"""Unit tests for contract-first architecture discovery gate and models."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from harness_agent.core.dispatch import transition_lifecycle_state
from harness_agent.core.models import (
    STATE_TOOL_ALLOWLIST,
    AgentLifecycleState,
    ArchitectureSpec,
    DirectoryLayoutSpec,
    TechStackSpec,
)
from harness_agent.core.orchestrator import AgentOrchestrator, ArchitectureDiscoveryEngine


def test_architecture_spec_pydantic_validation() -> None:
    """Verify ArchitectureSpec instantiates cleanly with default layout and generates markdown."""
    spec = ArchitectureSpec(
        project_name="my_test_service",
        description="A robust distributed message bus test service.",
        tech_stack=TechStackSpec(
            primary_language="python",
            language_version=">=3.11",
            frameworks=["FastAPI", "Click"],
            persistence="PostgreSQL",
            vector_db="Chroma",
            api_protocols=["REST", "CLI"],
        ),
        approved=True,
    )

    # Verify default layout
    assert spec.layout.src_dir == "src"
    assert spec.layout.tests_unit_dir == "tests/unit"
    assert spec.layout.tests_integration_dir == "tests/integration"
    assert spec.layout.docs_dir == "docs"
    assert spec.approved is True

    # Verify to_markdown_blueprint
    markdown = spec.to_markdown_blueprint()
    assert "# Architecture Blueprint: my_test_service" in markdown
    assert "## 1. Overview" in markdown
    assert "A robust distributed message bus test service." in markdown
    assert "## 2. Directory Layout Contract" in markdown
    assert "`src`" in markdown
    assert "`tests/unit`" in markdown
    assert "`tests/integration`" in markdown
    assert "## 3. Technology Stack" in markdown
    assert "FastAPI, Click" in markdown
    assert "PostgreSQL" in markdown
    assert "Chroma" in markdown
    assert "## 4. Coding & Architecture Standards" in markdown
    assert "## 5. Specification Status" in markdown
    assert "**Approved:** Yes" in markdown

    # Verify validation failure when required fields are missing
    with pytest.raises(ValidationError):
        ArchitectureSpec.model_validate({"project_name": "missing_description"})


def test_discovery_to_planning_transition_blocked_without_spec() -> None:
    """Attempt transition from DISCOVERY to PLANNING without valid spec."""
    allowed, new_state, msg = transition_lifecycle_state(
        current_state=AgentLifecycleState.DISCOVERY,
        target_state=AgentLifecycleState.PLANNING,
        architecture_spec=None,
        spec_validated=False,
    )
    assert allowed is False
    assert new_state == AgentLifecycleState.DISCOVERY
    assert "Architecture specification must be populated and validated" in msg


def test_discovery_to_planning_transition_allowed_with_spec() -> None:
    """Provide valid ArchitectureSpec or spec_validated=True and verify transition succeeds."""
    spec = ArchitectureSpec(
        project_name="demo_project",
        description="Demonstration project for FSM discovery transition.",
    )

    # 1. Using ArchitectureSpec instance
    allowed, new_state, msg = transition_lifecycle_state(
        current_state=AgentLifecycleState.DISCOVERY,
        target_state=AgentLifecycleState.PLANNING,
        architecture_spec=spec,
    )
    assert allowed is True
    assert new_state == AgentLifecycleState.PLANNING
    assert "Architecture specification validated" in msg

    # 2. Using valid dict
    allowed_dict, new_state_dict, _ = transition_lifecycle_state(
        current_state=AgentLifecycleState.DISCOVERY,
        target_state=AgentLifecycleState.PLANNING,
        architecture_spec={
            "project_name": "dict_project",
            "description": "Valid dictionary spec",
        },
    )
    assert allowed_dict is True
    assert new_state_dict == AgentLifecycleState.PLANNING

    # 3. Using spec_validated=True
    allowed_flag, new_state_flag, _ = transition_lifecycle_state(
        current_state=AgentLifecycleState.DISCOVERY,
        target_state=AgentLifecycleState.PLANNING,
        spec_validated=True,
    )
    assert allowed_flag is True
    assert new_state_flag == AgentLifecycleState.PLANNING


def test_discovery_state_tool_allowlist() -> None:
    """Assert discovery state allowlist includes observation tools and excludes mutations."""
    discovery_tools = STATE_TOOL_ALLOWLIST[AgentLifecycleState.DISCOVERY]

    # Required discovery tools
    assert "ask_question" in discovery_tools
    assert "read_file" in discovery_tools
    assert "view_file" in discovery_tools
    assert "search_web" in discovery_tools
    assert "read_url_content" in discovery_tools

    # Code mutation tools MUST be completely absent
    assert "apply_patch" not in discovery_tools
    assert "replace_file_content" not in discovery_tools
    assert "multi_replace_file_content" not in discovery_tools
    assert "run_command" not in discovery_tools
    assert "invoke_subagent" not in discovery_tools
    assert "define_subagent" not in discovery_tools


def test_save_and_load_architecture_blueprint(tmp_path: Path) -> None:
    """Test save_architecture_blueprint writes files and check_existing_architecture reloads."""
    spec = ArchitectureSpec(
        project_name="tmp_test_project",
        description="Architecture spec for tmp_path testing.",
        layout=DirectoryLayoutSpec(
            src_dir="src",
            tests_unit_dir="tests/unit",
            tests_integration_dir="tests/integration",
        ),
        tech_stack=TechStackSpec(
            primary_language="python",
            language_version=">=3.10",
            frameworks=["PyTest"],
            persistence="SQLite",
        ),
        approved=True,
    )

    # Save blueprint to real temporary directory filesystem
    json_path, md_path = AgentOrchestrator.save_architecture_blueprint(
        spec=spec,
        repo_root=tmp_path,
    )

    assert json_path.is_file()
    assert md_path.is_file()
    assert json_path == tmp_path / ".ai" / "context" / "architecture_spec.json"
    assert md_path == tmp_path / ".ai" / "context" / "architecture.md"

    # Reload via AgentOrchestrator and ArchitectureDiscoveryEngine
    loaded_spec = AgentOrchestrator.check_existing_architecture(repo_root=tmp_path)
    assert loaded_spec is not None
    assert loaded_spec.project_name == "tmp_test_project"
    assert loaded_spec.description == "Architecture spec for tmp_path testing."
    assert loaded_spec.tech_stack.persistence == "SQLite"

    engine_loaded = ArchitectureDiscoveryEngine.check_existing_architecture(repo_root=tmp_path)
    assert engine_loaded is not None
    assert engine_loaded.project_name == loaded_spec.project_name

    # Test run_discovery_flow reuse of existing architecture
    flow_spec = AgentOrchestrator().run_discovery_flow(repo_root=tmp_path)
    assert flow_spec.project_name == "tmp_test_project"


def test_save_and_load_architecture_blueprint_from_markdown_fallback(tmp_path: Path) -> None:
    """Test fallback loading from architecture.md when architecture_spec.json is not present."""
    context_dir = tmp_path / ".ai" / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    md_path = context_dir / "architecture.md"
    md_path.write_text(
        "# Architecture Blueprint\nSome initial architecture details.",
        encoding="utf-8",
    )

    loaded_spec = AgentOrchestrator.check_existing_architecture(repo_root=tmp_path)
    assert loaded_spec is not None
    assert loaded_spec.project_name == tmp_path.name
    assert loaded_spec.approved is True
