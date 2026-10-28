"""Dynamic Project Skill Auto-Scaffolder and Technology Detection."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Standard technology mapping rules: (manifest_pattern, tech_name, category)
TECH_CATALOG = [
    # Backend
    ("fastapi", "fastapi", "backend", "FastAPI web framework integration and endpoint dev."),
    ("alembic", "alembic", "database", "Alembic database migrations and schema management."),
    ("flask", "flask", "backend", "Flask lightweight web application architecture."),
    ("django", "django", "backend", "Django web framework and ORM conventions."),
    ("sqlalchemy", "sqlalchemy", "database", "SQLAlchemy ORM and database access layers."),
    # AI / ML
    ("torch", "pytorch", "ai_ml", "PyTorch model architecture and tensor operations."),
    ("pytorch", "pytorch", "ai_ml", "PyTorch model architecture and tensor operations."),
    ("transformers", "transformers", "ai_ml", "Hugging Face Transformers model workflows."),
    ("langchain", "langchain", "ai_ml", "LangChain LLM orchestration and chain composition."),
    # Frontend (package.json)
    ("react", "react", "frontend", "React component architecture and state management."),
    ("vue", "vue", "frontend", "Vue.js reactive components and state lifecycle."),
    ("next", "nextjs", "frontend", "Next.js server-side rendering and routing."),
    # DevOps
    ("dockerfile", "docker", "devops", "Containerization and multi-stage Docker builds."),
]


class DetectedTechnology(BaseModel):
    """Represents a technology or framework detected in the repository."""

    name: str = Field(
        ...,
        description="Technology or framework name (e.g., fastapi, alembic, pytorch, react)",
    )
    category: str = Field(..., description="Category (backend, database, frontend, ai_ml, devops)")
    confidence: float = Field(default=1.0, description="Detection confidence 0.0 to 1.0")
    source_file: str = Field(
        ...,
        description="Manifest or file where detected (e.g. pyproject.toml, package.json)",
    )


class ProjectSkillAutoScaffolder:
    """Scans repository dependencies and auto-scaffolds standardized skills in .agents/skills/."""

    def __init__(self, repo_root: Path, skills_dir: Optional[Path] = None) -> None:
        self.repo_root = Path(repo_root)
        self.skills_dir = (
            Path(skills_dir) if skills_dir else (self.repo_root / ".agents" / "skills")
        )

    def _parse_pyproject(self, path: Path) -> List[str]:
        """Extract dependency strings from pyproject.toml."""
        try:
            try:
                import tomllib

                with open(path, "rb") as f:
                    data = tomllib.load(f)
            except ImportError:
                import tomli as tomllib  # type: ignore

                with open(path, "rb") as f:
                    data = tomllib.load(f)

            found: List[str] = []
            project = data.get("project", {})
            deps = project.get("dependencies", [])
            found.extend(deps)

            optional_deps = project.get("optional-dependencies", {})
            for group in optional_deps.values():
                if isinstance(group, list):
                    found.extend(group)

            tool = data.get("tool", {})
            poetry = tool.get("poetry", {})
            poetry_deps = poetry.get("dependencies", {})
            if isinstance(poetry_deps, dict):
                found.extend(poetry_deps.keys())

            return [str(d).lower() for d in found]
        except Exception as exc:
            logger.warning("Failed to parse pyproject.toml at %s: %s", path, exc)
            return []

    def _parse_requirements(self, path: Path) -> List[str]:
        """Extract dependency names from requirements.txt."""
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            lines = []
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                lines.append(line.lower())
            return lines
        except Exception as exc:
            logger.warning("Failed to parse requirements file at %s: %s", path, exc)
            return []

    def _parse_package_json(self, path: Path) -> List[str]:
        """Extract dependencies from package.json."""
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            data = json.loads(content)
            deps = []
            for key in ("dependencies", "devDependencies", "peerDependencies"):
                d = data.get(key)
                if isinstance(d, dict):
                    deps.extend([k.lower() for k in d.keys()])
            return deps
        except Exception as exc:
            logger.warning("Failed to parse package.json at %s: %s", path, exc)
            return []

    def detect_technologies(self) -> List[DetectedTechnology]:
        """Inspects pyproject.toml, requirements.txt, package.json, Dockerfile, etc."""
        detected: Dict[str, DetectedTechnology] = {}

        # 1. pyproject.toml
        pyproject_path = self.repo_root / "pyproject.toml"
        if pyproject_path.is_file():
            py_deps = self._parse_pyproject(pyproject_path)
            for dep in py_deps:
                for token, tech_name, cat, _ in TECH_CATALOG:
                    if token in dep and tech_name not in detected:
                        detected[tech_name] = DetectedTechnology(
                            name=tech_name,
                            category=cat,
                            confidence=1.0,
                            source_file="pyproject.toml",
                        )

        # 2. requirements.txt and *.txt requirements in root
        for req_path in self.repo_root.glob("*requirement*.txt"):
            if req_path.is_file():
                req_deps = self._parse_requirements(req_path)
                for dep in req_deps:
                    for token, tech_name, cat, _ in TECH_CATALOG:
                        if token in dep and tech_name not in detected:
                            detected[tech_name] = DetectedTechnology(
                                name=tech_name,
                                category=cat,
                                confidence=1.0,
                                source_file=req_path.name,
                            )

        # 3. package.json
        pkg_json_path = self.repo_root / "package.json"
        if pkg_json_path.is_file():
            pkg_deps = self._parse_package_json(pkg_json_path)
            for dep in pkg_deps:
                for token, tech_name, cat, _ in TECH_CATALOG:
                    if token in dep and tech_name not in detected:
                        detected[tech_name] = DetectedTechnology(
                            name=tech_name,
                            category=cat,
                            confidence=1.0,
                            source_file="package.json",
                        )

        # 4. Dockerfile
        dockerfile_path = self.repo_root / "Dockerfile"
        if dockerfile_path.is_file() and "docker" not in detected:
            detected["docker"] = DetectedTechnology(
                name="docker",
                category="devops",
                confidence=1.0,
                source_file="Dockerfile",
            )

        return list(detected.values())

    def _generate_skill_content(self, tech: DetectedTechnology) -> str:
        """Generate standardized SKILL.md markdown with valid YAML frontmatter."""
        description = f"Standardized project skill and best practices for {tech.name}."
        for _, tech_name, _, desc in TECH_CATALOG:
            if tech_name == tech.name:
                description = desc
                break

        frontmatter: Dict[str, Any] = {
            "name": tech.name,
            "description": description,
        }
        yaml_header = yaml.safe_dump(frontmatter, sort_keys=False).strip()

        content = (
            f"---\n{yaml_header}\n---\n\n"
            f"# {tech.name.capitalize()} Skill Guide\n\n"
            f"## Overview\n"
            f"{description}\n\n"
            f"- **Category**: {tech.category}\n"
            f"- **Detected Source**: {tech.source_file}\n\n"
            f"## Standards & Guidelines\n"
            f"1. Follow standard clean code conventions when working with {tech.name}.\n"
            f"2. Maintain strict modularity and defensive error handling.\n"
            f"3. Run automated tests and validation suites before completing tasks.\n"
        )
        return content

    def scaffold_skill_if_missing(self, tech: DetectedTechnology) -> Optional[Path]:
        """Creates .agents/skills/<tech-name>/SKILL.md if not already present."""
        tech_dir = self.skills_dir / tech.name
        skill_file = tech_dir / "SKILL.md"

        if skill_file.exists():
            logger.info("Skill %s already exists at %s, skipping.", tech.name, skill_file)
            return None

        tech_dir.mkdir(parents=True, exist_ok=True)
        content = self._generate_skill_content(tech)

        # Verify YAML frontmatter is valid before writing
        parts = content.split("---")
        if len(parts) >= 3:
            yaml.safe_load(parts[1])

        skill_file.write_text(content, encoding="utf-8")
        logger.info("Scaffolded new skill for %s at %s", tech.name, skill_file)
        return skill_file

    def scan_and_scaffold(self) -> List[Path]:
        """Detects technologies and scaffolds missing skills, returning created skill paths."""
        technologies = self.detect_technologies()
        scaffolded: List[Path] = []
        for tech in technologies:
            path = self.scaffold_skill_if_missing(tech)
            if path:
                scaffolded.append(path)
        return scaffolded
