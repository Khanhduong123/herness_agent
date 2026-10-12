"""Unit tests for the jupyter-notebook skill.

Verifies:
1. Skill frontmatter and referenced files existence.
2. Notebook templates JSON and schema conformance (v4).
3. new_notebook.py scaffold script functions and CLI execution.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

# Calculate repo root directly from test file location
REPO_ROOT = Path(__file__).resolve().parents[2]

SCRIPTS_DIR = (
    Path(__file__).resolve().parents[2] / ".agents" / "skills" / "jupyter-notebook" / "scripts"
)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import new_notebook  # noqa: E402


@pytest.fixture
def skill_dir() -> Path:
    return REPO_ROOT / ".agents" / "skills" / "jupyter-notebook"


# -----------------------------------------------------------------------------
# Subtask 01: Skill Structure & Frontmatter Validation
# -----------------------------------------------------------------------------


def test_skill_frontmatter_and_discovery(skill_dir: Path) -> None:
    """Verifies that SKILL.md contains valid YAML frontmatter and required fields."""
    skill_file = skill_dir / "SKILL.md"
    assert skill_file.is_file(), f"Missing SKILL.md at {skill_file}"

    content = skill_file.read_text(encoding="utf-8")
    parts = content.split("---")
    assert len(parts) >= 3, "SKILL.md must have valid YAML frontmatter surrounded by '---'"

    frontmatter_text = parts[1]
    data = yaml.safe_load(frontmatter_text)
    assert isinstance(data, dict), "Parsed frontmatter must be a dictionary"
    assert data.get("name") == "jupyter-notebook", "Skill name must be 'jupyter-notebook'"
    assert bool(data.get("description")), "Skill description must be non-empty"


def test_referenced_files_exist(skill_dir: Path) -> None:
    """Verifies that all assets, references, and scripts declared in SKILL.md exist on disk."""
    expected_references = [
        "references/experiment-patterns.md",
        "references/tutorial-patterns.md",
        "references/notebook-structure.md",
        "references/quality-checklist.md",
        "scripts/new_notebook.py",
        "assets/experiment-template.ipynb",
        "assets/tutorial-template.ipynb",
        "assets/jupyter-small.svg",
        "assets/jupyter.png",
        "agents/openai.yaml",
    ]
    for rel_path in expected_references:
        target = skill_dir / rel_path
        assert target.exists(), f"Expected file {rel_path} does not exist at {target}"


def test_openai_yaml_metadata(skill_dir: Path) -> None:
    """Verifies that agents/openai.yaml exists and parses cleanly as valid YAML."""
    openai_yaml = skill_dir / "agents" / "openai.yaml"
    assert openai_yaml.is_file(), f"Missing openai.yaml at {openai_yaml}"

    data = yaml.safe_load(openai_yaml.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "openai.yaml must parse as a dictionary"
    assert "interface" in data, "openai.yaml must contain 'interface' mapping"
    interface = data["interface"]
    assert interface.get("display_name") == "Jupyter Notebooks"
    assert bool(interface.get("short_description"))
    assert bool(interface.get("default_prompt"))


# -----------------------------------------------------------------------------
# Subtask 02: Notebook Templates Validity
# -----------------------------------------------------------------------------


def _validate_notebook_schema(data: dict[str, Any]) -> None:
    """Helper to validate Jupyter notebook v4 schema without external nbformat dependency."""
    assert "cells" in data, "Notebook missing 'cells' key"
    assert "metadata" in data, "Notebook missing 'metadata' key"
    assert "nbformat" in data, "Notebook missing 'nbformat' key"
    assert "nbformat_minor" in data, "Notebook missing 'nbformat_minor' key"

    assert isinstance(data["cells"], list), "'cells' must be a list"
    assert len(data["cells"]) > 0, "Notebook must have at least one cell"
    assert data["nbformat"] >= 4, f"nbformat version {data['nbformat']} must be >= 4"
    assert data["nbformat_minor"] >= 2, f"nbformat_minor {data['nbformat_minor']} must be >= 2"

    first_cell = data["cells"][0]
    assert isinstance(first_cell, dict), "First cell must be a dict"
    assert first_cell.get("cell_type") == "markdown", "First cell must be markdown"
    source = first_cell.get("source", [])
    if isinstance(source, list):
        first_line = source[0] if source else ""
    else:
        first_line = str(source)
    assert first_line.startswith("# "), f"First cell must start with '# ': {first_line}"

    metadata = data["metadata"]
    assert isinstance(metadata, dict), "Notebook metadata must be a dict"
    assert (
        "language_info" in metadata or "kernelspec" in metadata
    ), "Notebook metadata must specify language_info or kernelspec"


def test_experiment_template_conformance(skill_dir: Path) -> None:
    """Validates experiment-template.ipynb JSON syntax, nbformat version, and cell structure."""
    template_path = skill_dir / "assets" / "experiment-template.ipynb"
    assert template_path.is_file(), f"Missing template at {template_path}"

    with template_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data, dict), "Template must be a JSON object"
    _validate_notebook_schema(data)
    first_line = data["cells"][0]["source"][0]
    assert "Experiment:" in first_line, f"Experiment title prefix expected in: {first_line}"


def test_tutorial_template_conformance(skill_dir: Path) -> None:
    """Validates tutorial-template.ipynb JSON syntax, nbformat version, and cell structure."""
    template_path = skill_dir / "assets" / "tutorial-template.ipynb"
    assert template_path.is_file(), f"Missing template at {template_path}"

    with template_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data, dict), "Template must be a JSON object"
    _validate_notebook_schema(data)
    first_line = data["cells"][0]["source"][0]
    assert "Tutorial:" in first_line, f"Tutorial title prefix expected in: {first_line}"


# -----------------------------------------------------------------------------
# Subtask 03: Scaffold Script & CLI Execution
# -----------------------------------------------------------------------------


def test_slugify() -> None:
    """Verifies that slugify properly cleans, normalizes, and falls back to 'notebook'."""
    assert new_notebook.slugify("My Experiment 123") == "my-experiment-123"
    assert new_notebook.slugify("Special @#$ Characters!") == "special-characters"
    assert new_notebook.slugify("   Leading and trailing   ") == "leading-and-trailing"
    assert new_notebook.slugify("Multiple---Hyphens___Under") == "multiple-hyphens-under"
    assert new_notebook.slugify("") == "notebook"
    assert new_notebook.slugify("   ") == "notebook"
    assert new_notebook.slugify("$$$###") == "notebook"
    assert new_notebook.slugify("A - B - C") == "a-b-c"


def test_load_template(skill_dir: Path) -> None:
    """Tests load_template for valid and invalid inputs."""
    exp_nb = new_notebook.load_template(skill_dir, "experiment")
    assert isinstance(exp_nb, dict)
    assert exp_nb["nbformat"] >= 4

    tut_nb = new_notebook.load_template(skill_dir, "tutorial")
    assert isinstance(tut_nb, dict)
    assert tut_nb["nbformat"] >= 4

    with pytest.raises(SystemExit):
        new_notebook.load_template(skill_dir / "nonexistent", "experiment")


def test_update_title_experiment_and_tutorial() -> None:
    """Verifies that update_title replaces the title and sets python 3.12 metadata."""
    nb_exp: dict[str, Any] = {
        "cells": [
            {"cell_type": "markdown", "source": ["# Old Title\n", "Some text"]},
            {"cell_type": "code", "source": ["print(1)"]},
        ],
        "metadata": {},
    }
    new_notebook.update_title(nb_exp, "experiment", "My Deep Analysis")
    assert nb_exp["cells"][0]["source"][0] == "# Experiment: My Deep Analysis\n"
    assert nb_exp["metadata"]["language_info"]["name"] == "python"
    assert nb_exp["metadata"]["language_info"]["version"] == "3.12"

    nb_tut: dict[str, Any] = {
        "cells": [
            {"cell_type": "markdown", "source": ["# Placeholder\n"]},
        ],
        "metadata": {},
    }
    new_notebook.update_title(nb_tut, "tutorial", "Getting Started")
    assert nb_tut["cells"][0]["source"][0] == "# Tutorial: Getting Started\n"

    # Edge cases
    with pytest.raises(SystemExit, match="Template notebook has no cells"):
        new_notebook.update_title({"cells": []}, "experiment", "Title")

    with pytest.raises(SystemExit, match="Template notebook must start with a markdown title cell"):
        new_notebook.update_title(
            {"cells": [{"cell_type": "code", "source": []}]}, "experiment", "Title"
        )


def test_default_output() -> None:
    """Verifies default_output generates expected relative path."""
    repo_root = Path("/fake/root")
    res = new_notebook.default_output(repo_root, "Test Notebook Title")
    expected = repo_root / "output" / "jupyter-notebook" / "test-notebook-title.ipynb"
    assert res == expected


def test_cli_scaffold_execution(skill_dir: Path, tmp_path: Path) -> None:
    """Tests execution of new_notebook.py CLI with --out, --title, and --kind."""
    script_path = skill_dir / "scripts" / "new_notebook.py"
    target_nb = tmp_path / "exp1.ipynb"

    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--kind",
            "experiment",
            "--title",
            "Ablation Run",
            "--out",
            str(target_nb),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert target_nb.is_file()

    with target_nb.open("r", encoding="utf-8") as f:
        content = json.load(f)
    assert content["cells"][0]["source"][0] == "# Experiment: Ablation Run\n"


def test_cli_overwrite_protection(skill_dir: Path, tmp_path: Path) -> None:
    """Tests that new_notebook.py refuses overwrite without --force, but succeeds with --force."""
    script_path = skill_dir / "scripts" / "new_notebook.py"
    target_nb = tmp_path / "protected.ipynb"

    # First run succeeds
    cmd_base = [sys.executable, str(script_path), "--title", "First Run", "--out", str(target_nb)]
    r1 = subprocess.run(cmd_base, capture_output=True, text=True, check=False)
    assert r1.returncode == 0

    # Second run without --force fails
    cmd_second = [
        sys.executable,
        str(script_path),
        "--title",
        "Second Run",
        "--out",
        str(target_nb),
    ]
    r2 = subprocess.run(cmd_second, capture_output=True, text=True, check=False)
    assert r2.returncode != 0
    assert "Refusing to overwrite existing file without --force" in (r2.stderr + r2.stdout)

    # Third run with --force succeeds
    cmd_forced = cmd_second + ["--force"]
    r3 = subprocess.run(cmd_forced, capture_output=True, text=True, check=False)
    assert r3.returncode == 0

    with target_nb.open("r", encoding="utf-8") as f:
        content = json.load(f)
    assert content["cells"][0]["source"][0] == "# Experiment: Second Run\n"


def test_cli_auto_create_parent_dirs(skill_dir: Path, tmp_path: Path) -> None:
    """Tests that new_notebook.py creates missing nested parent directories."""
    script_path = skill_dir / "scripts" / "new_notebook.py"
    target_nb = tmp_path / "nested" / "sub" / "folder" / "deep_test.ipynb"

    result = subprocess.run(
        [sys.executable, str(script_path), "--title", "Deep Nesting", "--out", str(target_nb)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert target_nb.is_file()
