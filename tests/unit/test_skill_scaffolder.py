"""Unit tests for ProjectSkillAutoScaffolder and DetectedTechnology."""

from pathlib import Path

import yaml

from harness_agent.core.skills import DetectedTechnology, ProjectSkillAutoScaffolder


def test_detect_python_fastapi_and_alembic(tmp_path: Path):
    """Verify FastAPI and Alembic are detected from pyproject.toml."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """[project]
name = "sample-app"
version = "0.1.0"
dependencies = [
    "fastapi>=0.100.0",
    "alembic==1.12.0",
    "uvicorn",
]
""",
        encoding="utf-8",
    )

    scaffolder = ProjectSkillAutoScaffolder(repo_root=tmp_path)
    detected = scaffolder.detect_technologies()

    tech_names = {t.name: t for t in detected}
    assert "fastapi" in tech_names
    assert tech_names["fastapi"].category == "backend"
    assert tech_names["fastapi"].source_file == "pyproject.toml"

    assert "alembic" in tech_names
    assert tech_names["alembic"].category == "database"
    assert tech_names["alembic"].source_file == "pyproject.toml"


def test_scaffold_creates_valid_skill_md(tmp_path: Path):
    """Verify generated SKILL.md contains valid YAML frontmatter and markdown structure."""
    skills_dir = tmp_path / ".agents" / "skills"
    scaffolder = ProjectSkillAutoScaffolder(repo_root=tmp_path, skills_dir=skills_dir)

    tech = DetectedTechnology(
        name="fastapi",
        category="backend",
        confidence=1.0,
        source_file="pyproject.toml",
    )

    created_path = scaffolder.scaffold_skill_if_missing(tech)
    assert created_path is not None
    assert created_path.exists()
    assert created_path.name == "SKILL.md"
    assert created_path.parent.name == "fastapi"

    content = created_path.read_text(encoding="utf-8")
    assert content.startswith("---")
    parts = content.split("---")
    assert len(parts) >= 3

    # Parse YAML frontmatter
    data = yaml.safe_load(parts[1])
    assert data["name"] == "fastapi"
    assert "description" in data
    assert "FastAPI" in data["description"]

    # Markdown body
    body = parts[2]
    assert "# Fastapi Skill Guide" in body or "# FastAPI Skill Guide" in body
    assert "- **Category**: backend" in body


def test_never_overwrites_existing_skill(tmp_path: Path):
    """Verify existing skill files are preserved untouched."""
    skills_dir = tmp_path / ".agents" / "skills"
    existing_dir = skills_dir / "fastapi"
    existing_dir.mkdir(parents=True, exist_ok=True)
    existing_skill = existing_dir / "SKILL.md"
    original_content = "---\nname: fastapi\ndescription: Custom pre-existing skill\n---\n# Custom"
    existing_skill.write_text(original_content, encoding="utf-8")

    scaffolder = ProjectSkillAutoScaffolder(repo_root=tmp_path, skills_dir=skills_dir)
    tech = DetectedTechnology(
        name="fastapi",
        category="backend",
        confidence=1.0,
        source_file="pyproject.toml",
    )

    created = scaffolder.scaffold_skill_if_missing(tech)
    assert created is None
    assert existing_skill.read_text(encoding="utf-8") == original_content


def test_scan_and_scaffold_e2e(tmp_path: Path):
    """Verify scan_and_scaffold detects requirements.txt, package.json, Dockerfile and scaffolds."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("torch>=2.0.0\nflask\n", encoding="utf-8")

    pkg_file = tmp_path / "package.json"
    pkg_file.write_text('{"dependencies": {"react": "^18.0.0"}}', encoding="utf-8")

    docker_file = tmp_path / "Dockerfile"
    docker_file.write_text("FROM python:3.11\n", encoding="utf-8")

    scaffolder = ProjectSkillAutoScaffolder(repo_root=tmp_path)
    created_paths = scaffolder.scan_and_scaffold()

    assert len(created_paths) == 4
    created_names = {p.parent.name for p in created_paths}
    assert "pytorch" in created_names
    assert "flask" in created_names
    assert "react" in created_names
    assert "docker" in created_names


def test_no_manifests_returns_empty(tmp_path: Path):
    """Verify empty directory yields empty detected list without error."""
    scaffolder = ProjectSkillAutoScaffolder(repo_root=tmp_path)
    detected = scaffolder.detect_technologies()
    assert detected == []
    created = scaffolder.scan_and_scaffold()
    assert created == []


def test_corrupt_manifest_handled_gracefully(tmp_path: Path):
    """Verify corrupt pyproject or package.json doesn't crash detection."""
    bad_pyproject = tmp_path / "pyproject.toml"
    bad_pyproject.write_text("corrupted [[[ toml", encoding="utf-8")

    bad_pkg = tmp_path / "package.json"
    bad_pkg.write_text("{not valid json", encoding="utf-8")

    docker_file = tmp_path / "Dockerfile"
    docker_file.write_text("FROM alpine\n", encoding="utf-8")

    scaffolder = ProjectSkillAutoScaffolder(repo_root=tmp_path)
    detected = scaffolder.detect_technologies()
    assert len(detected) == 1
    assert detected[0].name == "docker"
