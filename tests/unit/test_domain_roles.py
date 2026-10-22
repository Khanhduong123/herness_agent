"""Unit tests for domain role specialization, domain boundary detection,
artifact validation gates, dispatch payload formatting, and worktree chaining.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_agent.core.dispatch import HerdrDispatcher
from harness_agent.core.models import (
    DOMAIN_PROFILES,
    ROLE_DEFAULT_SKILLS,
    ROLE_TOOL_ALLOWLIST,
    AgentRole,
    SubTask,
    TaskStatus,
)
from harness_agent.core.orchestrator import AgentOrchestrator, validate_output_artifacts
from harness_agent.research import detect_domain_role, scan_project_domain_boundaries

# ---------------------------------------------------------------------------
# 1. Role & Model Serialization Tests
# ---------------------------------------------------------------------------


def test_agent_role_enum_values() -> None:
    """Verify standard and domain-specific AgentRole enum values."""
    assert AgentRole.DATABASE == "database"
    assert AgentRole.BACKEND == "backend"
    assert AgentRole.FRONTEND == "frontend"
    assert AgentRole.DEVOPS == "devops"
    assert AgentRole.AI_ML == "ai_ml"


def test_agent_role_normalization_case_and_hyphen() -> None:
    """Verify normalization of hyphenated or mixed-case role strings."""
    assert AgentRole("ai-ml") == AgentRole.AI_ML
    assert AgentRole("AI-ML") == AgentRole.AI_ML
    assert AgentRole("AI_ML") == AgentRole.AI_ML
    assert AgentRole("backend") == AgentRole.BACKEND
    assert AgentRole("BACKEND") == AgentRole.BACKEND
    assert AgentRole("database") == AgentRole.DATABASE
    assert AgentRole("FRONTEND") == AgentRole.FRONTEND
    assert AgentRole("devops") == AgentRole.DEVOPS


def test_role_tool_allowlist_and_default_skills() -> None:
    """Verify domain roles exist in tool allowlists and default skills mappings."""
    domain_roles = [
        AgentRole.DATABASE,
        AgentRole.BACKEND,
        AgentRole.FRONTEND,
        AgentRole.DEVOPS,
        AgentRole.AI_ML,
    ]
    for role in domain_roles:
        assert role in ROLE_TOOL_ALLOWLIST
        assert "view_file" in ROLE_TOOL_ALLOWLIST[role]
        assert "apply_patch" in ROLE_TOOL_ALLOWLIST[role]
        assert "write_to_file" in ROLE_TOOL_ALLOWLIST[role]

    assert AgentRole.BACKEND in ROLE_DEFAULT_SKILLS
    assert "sdlc-api-interface-design" in ROLE_DEFAULT_SKILLS[AgentRole.BACKEND]
    assert "sdlc-clean-code-standards" in ROLE_DEFAULT_SKILLS[AgentRole.BACKEND]

    assert AgentRole.FRONTEND in ROLE_DEFAULT_SKILLS
    assert "sdlc-frontend-ui-engineering" in ROLE_DEFAULT_SKILLS[AgentRole.FRONTEND]

    assert AgentRole.AI_ML in ROLE_DEFAULT_SKILLS
    assert "pytorch-patterns" in ROLE_DEFAULT_SKILLS[AgentRole.AI_ML]

    assert AgentRole.DATABASE in ROLE_DEFAULT_SKILLS
    assert "sdlc-clean-code-standards" in ROLE_DEFAULT_SKILLS[AgentRole.DATABASE]

    assert AgentRole.DEVOPS in ROLE_DEFAULT_SKILLS
    assert "sdlc-clean-code-standards" in ROLE_DEFAULT_SKILLS[AgentRole.DEVOPS]


def test_subtask_schema_serialization_with_domain_fields() -> None:
    """Verify SubTask schema serializes and deserializes target_paths, output_artifacts,

    and injected_context.
    """
    subtask = SubTask(
        id="task_backend_api",
        name="Backend API Implementation",
        role=AgentRole.BACKEND,
        instruction="Implement user authentication API",
        target_paths=["backend/api/v1/", "services/auth/"],
        output_artifacts=["backend/api/v1/auth.py", "docs/auth_spec.json"],
        injected_context=["database/schema.sql"],
    )

    data = subtask.model_dump()
    assert data["id"] == "task_backend_api"
    assert data["role"] == AgentRole.BACKEND
    assert data["target_paths"] == ["backend/api/v1/", "services/auth/"]
    assert data["output_artifacts"] == ["backend/api/v1/auth.py", "docs/auth_spec.json"]
    assert data["injected_context"] == ["database/schema.sql"]

    json_str = subtask.model_dump_json()
    restored = SubTask.model_validate_json(json_str)
    assert restored.id == subtask.id
    assert restored.role == AgentRole.BACKEND
    assert restored.target_paths == subtask.target_paths
    assert restored.output_artifacts == subtask.output_artifacts
    assert restored.injected_context == subtask.injected_context


# ---------------------------------------------------------------------------
# 2. Domain Boundary Detection Tests
# ---------------------------------------------------------------------------


def test_detect_domain_role_matches_domain_profiles() -> None:
    """Verify detect_domain_role matches file paths against DOMAIN_PROFILES."""
    assert AgentRole.DATABASE in DOMAIN_PROFILES
    assert AgentRole.BACKEND in DOMAIN_PROFILES
    assert AgentRole.FRONTEND in DOMAIN_PROFILES
    assert AgentRole.DEVOPS in DOMAIN_PROFILES
    assert AgentRole.AI_ML in DOMAIN_PROFILES

    # Database matching
    assert detect_domain_role(["migrations/0001_initial.py"]) == AgentRole.DATABASE
    assert detect_domain_role(["models/user.py", "alembic/env.py"]) == AgentRole.DATABASE
    assert detect_domain_role(["prisma/schema.prisma"]) == AgentRole.DATABASE

    # Backend matching
    assert detect_domain_role(["backend/api/v1/routes.py"]) == AgentRole.BACKEND
    assert detect_domain_role(["services/payment_service.py"]) == AgentRole.BACKEND
    assert detect_domain_role(["routers/items.py", "api/health.py"]) == AgentRole.BACKEND

    # Frontend matching
    assert detect_domain_role(["frontend/src/App.tsx"]) == AgentRole.FRONTEND
    assert detect_domain_role(["src/components/Button.jsx"]) == AgentRole.FRONTEND
    assert detect_domain_role(["src/pages/Dashboard.vue"]) == AgentRole.FRONTEND
    assert detect_domain_role(["src/features/auth/Login.tsx"]) == AgentRole.FRONTEND

    # DevOps matching
    assert detect_domain_role(["Dockerfile"]) == AgentRole.DEVOPS
    assert detect_domain_role(["docker-compose.yml"]) == AgentRole.DEVOPS
    assert detect_domain_role([".github/workflows/ci.yml"]) == AgentRole.DEVOPS
    assert detect_domain_role(["k8s/deployment.yaml"]) == AgentRole.DEVOPS

    # AI / ML matching
    assert detect_domain_role(["training/train.py"]) == AgentRole.AI_ML
    assert detect_domain_role(["pipelines/eval_pipeline.py"]) == AgentRole.AI_ML
    assert detect_domain_role(["notebooks/exploration.ipynb"]) == AgentRole.AI_ML


def test_detect_domain_role_fallback_to_coder() -> None:
    """Verify fallback to AgentRole.CODER on empty, unmatched, or ambiguous paths."""
    # Empty list
    assert detect_domain_role([]) == AgentRole.CODER

    # Generic unmatched paths
    assert detect_domain_role(["README.md", "pyproject.toml"]) == AgentRole.CODER
    assert detect_domain_role(["src/utils/helpers.py"]) == AgentRole.CODER

    # Ambiguous tie: one database pattern vs one frontend pattern
    tie_paths = ["migrations/001.sql", "frontend/src/App.js"]
    assert detect_domain_role(tie_paths) == AgentRole.CODER


def test_scan_project_domain_boundaries(tmp_path: Path) -> None:
    """Verify scanning directory structure groups files into DOMAIN_PROFILES."""
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "0001_init.sql").write_text("CREATE TABLE users;", encoding="utf-8")

    (tmp_path / "backend" / "api").mkdir(parents=True)
    (tmp_path / "backend" / "api" / "routes.py").write_text("# API routes", encoding="utf-8")

    (tmp_path / "frontend" / "src").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "App.js").write_text("// React app", encoding="utf-8")

    (tmp_path / "Dockerfile").write_text("FROM python:3.11", encoding="utf-8")

    (tmp_path / "training").mkdir()
    (tmp_path / "training" / "train.py").write_text("import torch", encoding="utf-8")

    boundaries = scan_project_domain_boundaries(tmp_path)
    assert any("migrations/0001_init.sql" in p for p in boundaries[AgentRole.DATABASE])
    assert any("backend/api/routes.py" in p for p in boundaries[AgentRole.BACKEND])
    assert any("frontend/src/App.js" in p for p in boundaries[AgentRole.FRONTEND])
    assert any("Dockerfile" in p for p in boundaries[AgentRole.DEVOPS])
    assert any("training/train.py" in p for p in boundaries[AgentRole.AI_ML])


# ---------------------------------------------------------------------------
# 3. Artifact Validation Gate Tests
# ---------------------------------------------------------------------------


def test_validate_output_artifacts_empty_declarations(tmp_path: Path) -> None:
    """Verify validation passes when no output artifacts are declared."""
    subtask = SubTask(
        id="task_no_artifacts",
        name="No artifacts",
        role=AgentRole.CODER,
        instruction="Do work",
        output_artifacts=[],
    )
    valid, err = validate_output_artifacts(subtask, str(tmp_path))
    assert valid is True
    assert err is None


def test_validate_output_artifacts_success(tmp_path: Path) -> None:
    """Verify validation passes when all declared output artifacts exist and are non-empty."""
    out_file1 = tmp_path / "schema.sql"
    out_file1.write_text("CREATE TABLE test (id INT);", encoding="utf-8")

    nested_dir = tmp_path / "generated" / "docs"
    nested_dir.mkdir(parents=True)
    out_file2 = nested_dir / "api.json"
    out_file2.write_text('{"openapi": "3.0.0"}', encoding="utf-8")

    subtask = SubTask(
        id="task_with_artifacts",
        name="Artifact producer",
        role=AgentRole.DATABASE,
        instruction="Generate schema and api spec",
        output_artifacts=["schema.sql", "generated/docs/api.json"],
    )
    valid, err = validate_output_artifacts(subtask, str(tmp_path))
    assert valid is True
    assert err is None


def test_validate_output_artifacts_missing_file(tmp_path: Path) -> None:
    """Verify validation fails when a declared output artifact is missing."""
    present_file = tmp_path / "schema.sql"
    present_file.write_text("CREATE TABLE test (id INT);", encoding="utf-8")

    subtask = SubTask(
        id="task_missing_art",
        name="Artifact producer",
        role=AgentRole.DATABASE,
        instruction="Generate artifacts",
        output_artifacts=["schema.sql", "missing_artifact.json"],
    )
    valid, err = validate_output_artifacts(subtask, str(tmp_path))
    assert valid is False
    assert err is not None
    assert "missing_artifact.json" in err
    assert "was not created" in err


def test_validate_output_artifacts_empty_file_zero_bytes(tmp_path: Path) -> None:
    """Verify validation fails when a declared output artifact is empty (0 bytes)."""
    empty_file = tmp_path / "empty_output.txt"
    empty_file.write_text("", encoding="utf-8")
    assert empty_file.stat().st_size == 0

    subtask = SubTask(
        id="task_zero_bytes",
        name="Zero byte producer",
        role=AgentRole.CODER,
        instruction="Generate artifact",
        output_artifacts=["empty_output.txt"],
    )
    valid, err = validate_output_artifacts(subtask, str(tmp_path))
    assert valid is False
    assert err is not None
    assert "empty_output.txt" in err
    assert "0 bytes" in err


def test_validate_output_artifacts_directory_not_file(tmp_path: Path) -> None:
    """Verify validation fails if the output artifact path points to a directory."""
    art_dir = tmp_path / "some_dir"
    art_dir.mkdir()

    subtask = SubTask(
        id="task_dir_artifact",
        name="Directory artifact",
        role=AgentRole.CODER,
        instruction="Generate dir",
        output_artifacts=["some_dir"],
    )
    valid, err = validate_output_artifacts(subtask, str(tmp_path))
    assert valid is False
    assert err is not None
    assert "is not a regular file" in err


# ---------------------------------------------------------------------------
# 4. Herdr Dispatch Payload Formatting Tests
# ---------------------------------------------------------------------------


def test_format_dispatch_payload_includes_all_domain_fields() -> None:
    """Verify format_dispatch_payload includes role, spec, target paths, skills,

    injected context, and output artifacts.
    """
    payload = HerdrDispatcher.format_dispatch_payload(
        role="Database Specialist Worker",
        spec_path=".ai/plans/subtasks/2026-10-22/subtask_01.md",
        prohibitions=["No ManageTask", "no full-file overwrite"],
        target="100% pytest pass",
        model="gemini-2.5-flash",
        target_paths=["migrations/", "models/schema.py"],
        required_skills=["sdlc-clean-code-standards", "sdlc-database-modeling"],
        injected_context=["docs/architecture_spec.md"],
        output_artifacts=["migrations/0001_initial.sql", "models/schema.py"],
    )

    lines = payload.splitlines()
    assert lines[0] == "[ROLE: Database Specialist Worker]"
    assert lines[1] == "Spec: .ai/plans/subtasks/2026-10-22/subtask_01.md"
    assert "Required Skills: sdlc-clean-code-standards, sdlc-database-modeling" in lines
    assert "Target Paths: migrations/, models/schema.py" in lines
    assert "Injected Context: docs/architecture_spec.md" in lines
    assert "Output Artifacts: migrations/0001_initial.sql, models/schema.py" in lines
    assert "Model: gemini-2.5-flash" in lines
    assert "Prohibitions: No ManageTask, no full-file overwrite" in lines
    assert "Target: 100% pytest pass" in lines


def test_format_dispatch_payload_omits_optional_when_empty() -> None:
    """Verify format_dispatch_payload omits optional fields when None or empty."""
    payload = HerdrDispatcher.format_dispatch_payload(
        role="Leaf Coder Worker",
        spec_path=".ai/plans/subtask_simple.md",
    )

    assert "Target Paths:" not in payload
    assert "Required Skills:" not in payload
    assert "Injected Context:" not in payload
    assert "Output Artifacts:" not in payload
    assert "Model:" not in payload
    assert "[ROLE: Leaf Coder Worker]" in payload
    assert "Spec: .ai/plans/subtask_simple.md" in payload
    assert "Prohibitions: No ManageTask, no background loops, no full-file overwrite." in payload


# ---------------------------------------------------------------------------
# 5. Worktree Chaining & Topological Ordering Tests
# ---------------------------------------------------------------------------


def test_topological_order_resolution() -> None:
    """Verify resolve_execution_order orders tasks topologically based on depends_on."""
    t1 = SubTask(id="task_1", name="Task 1", instruction="Step 1")
    t2 = SubTask(id="task_2", name="Task 2", instruction="Step 2", depends_on=["task_1"])
    t3 = SubTask(id="task_3", name="Task 3", instruction="Step 3", depends_on=["task_2"])
    t4 = SubTask(id="task_4", name="Task 4", instruction="Step 4", depends_on=["task_1"])

    orchestrator = AgentOrchestrator()
    # Pass unordered
    ordered = orchestrator.resolve_execution_order([t3, t4, t2, t1])
    ordered_ids = [t.id for t in ordered]

    assert ordered_ids.index("task_1") < ordered_ids.index("task_2")
    assert ordered_ids.index("task_2") < ordered_ids.index("task_3")
    assert ordered_ids.index("task_1") < ordered_ids.index("task_4")


def test_topological_order_cycle_detection() -> None:
    """Verify resolve_execution_order raises ValueError on circular dependency."""
    t1 = SubTask(id="task_a", name="A", instruction="A", depends_on=["task_b"])
    t2 = SubTask(id="task_b", name="B", instruction="B", depends_on=["task_a"])

    orchestrator = AgentOrchestrator()
    with pytest.raises(ValueError, match="Cyclic dependency detected"):
        orchestrator.resolve_execution_order([t1, t2])


def test_resolve_worktree_base_ref_no_dependencies() -> None:
    """Verify resolve_worktree_base_ref returns default base ref when no dependencies."""
    task = SubTask(id="task_init", name="Init", instruction="Init", depends_on=[])
    base_ref = AgentOrchestrator.resolve_worktree_base_ref(
        task, default_base_ref="feat/dynamic-roles"
    )
    assert base_ref == "feat/dynamic-roles"


def test_resolve_worktree_base_ref_with_dependencies() -> None:
    """Verify resolve_worktree_base_ref resolves to the upstream task branch."""
    task = SubTask(
        id="task_backend",
        name="Backend",
        instruction="Backend",
        depends_on=["task_db", "task_schema"],
    )

    # When no statuses provided, it picks the last dependency
    base_ref = AgentOrchestrator.resolve_worktree_base_ref(task)
    assert base_ref == "agent/task_schema"

    # With task_statuses check: only COMPLETED tasks qualify
    statuses = {
        "task_db": TaskStatus.COMPLETED,
        "task_schema": TaskStatus.PENDING,
    }
    base_ref_status = AgentOrchestrator.resolve_worktree_base_ref(
        task, task_statuses=statuses, default_base_ref="main"
    )
    # task_schema is pending, so it falls back to the completed task_db
    assert base_ref_status == "agent/task_db"


def test_resolve_worktree_base_ref_all_dependencies_pending() -> None:
    """Verify resolve_worktree_base_ref falls back to default if all dependencies pending."""
    task = SubTask(
        id="task_followup",
        name="Followup",
        instruction="Followup",
        depends_on=["task_dep1", "task_dep2"],
    )
    statuses = {
        "task_dep1": TaskStatus.PENDING,
        "task_dep2": TaskStatus.FAILED,
    }
    base_ref = AgentOrchestrator.resolve_worktree_base_ref(
        task, task_statuses=statuses, default_base_ref="feat/my-feature"
    )
    assert base_ref == "feat/my-feature"
