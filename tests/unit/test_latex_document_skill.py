"""Unit tests for the latex-document-skill.

Verifies:
1. Skill directory and SKILL.md metadata integrity (YAML frontmatter, name, description).
2. Template existence and AST/syntax validation (ATS resumes, academic CV, all .tex templates).
3. Compiler bridge logic (compile_runner.py):
   - inspect_environment and CLI --check flag
   - Syntax validation fallback and --dry-run-ok
   - Engine auto-detection logic
   - Mocked native compiler invocation and error handling
   - Mocked docker compiler execution and error handling
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / ".agents" / "skills" / "latex-document-skill"
SCRIPTS_DIR = SKILL_DIR / "scripts"
TEMPLATES_DIR = SKILL_DIR / "assets" / "templates"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import compile_runner  # noqa: E402
import validate_latex  # noqa: E402


@pytest.fixture
def skill_path() -> Path:
    return SKILL_DIR


@pytest.fixture
def templates_path() -> Path:
    return TEMPLATES_DIR


# ---------------------------------------------------------------------------
# 1. Skill Discovery & Metadata Integrity
# ---------------------------------------------------------------------------


def test_skill_directory_and_frontmatter(skill_path: Path) -> None:
    """Verify that SKILL.md exists with valid YAML frontmatter and required fields."""
    skill_file = skill_path / "SKILL.md"
    assert skill_file.is_file(), f"Missing SKILL.md at {skill_file}"

    content = skill_file.read_text(encoding="utf-8")
    parts = content.split("---")
    assert len(parts) >= 3, "SKILL.md must have valid YAML frontmatter surrounded by '---'"

    frontmatter = yaml.safe_load(parts[1])
    assert isinstance(frontmatter, dict), "Frontmatter must parse as a dictionary"
    assert frontmatter.get("name") == "latex-document-skill"
    assert "latex" in frontmatter.get("description", "").lower()

    # Verify expected subdirectories exist
    assert (skill_path / "scripts").is_dir()
    assert (skill_path / "assets" / "templates").is_dir()
    assert (skill_path / "references").is_dir()


# ---------------------------------------------------------------------------
# 2. Template Existence & Validation
# ---------------------------------------------------------------------------


def test_ats_resumes_and_academic_cv_exist(templates_path: Path) -> None:
    """Verify all 5 ATS resume templates and academic CV template exist."""
    required_templates = [
        "resume-classic-ats.tex",
        "resume-modern-professional.tex",
        "resume-executive.tex",
        "resume-technical.tex",
        "resume-entry-level.tex",
        "academic-cv.tex",
    ]
    for template_name in required_templates:
        tpl_file = templates_path / template_name
        assert (
            tpl_file.is_file()
        ), f"Required template {template_name} not found in {templates_path}"


def test_all_templates_pass_validate_latex(templates_path: Path) -> None:
    """Validate all template .tex files using validate_latex to ensure 0 syntax errors."""
    tex_files = list(templates_path.glob("*.tex"))
    assert len(tex_files) >= 6, "Expected at least 6 template files"

    for tex_file in tex_files:
        errors = validate_latex.validate_file(
            str(tex_file),
            preamble_commands=set(),
            allow_full_document=True,
        )
        assert len(errors) == 0, f"Validation errors in {tex_file.name}: {[str(e) for e in errors]}"


def test_validate_latex_catches_syntax_errors(tmp_path: Path) -> None:
    """Verify that validate_latex correctly detects unmatched environments."""
    broken_file = tmp_path / "broken.tex"
    broken_file.write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\begin{itemize}\n\\item Test\n\\end{document}",
        encoding="utf-8",
    )
    errors = validate_latex.validate_file(
        str(broken_file), preamble_commands=set(), allow_full_document=True
    )
    assert len(errors) > 0
    categories = {e.category for e in errors}
    assert "ENV_UNCLOSED" in categories or "ENV_MISMATCH" in categories


# ---------------------------------------------------------------------------
# 3. Engine Detection Logic
# ---------------------------------------------------------------------------


def test_auto_detect_engine_xelatex(tmp_path: Path) -> None:
    """Verify xelatex is detected when fontspec or xeCJK is used."""
    tex_file = tmp_path / "xetex_doc.tex"
    tex_file.write_text(
        "\\documentclass{article}\n\\usepackage{fontspec}\n\\begin{document}Hello\\end{document}",
        encoding="utf-8",
    )
    assert compile_runner.auto_detect_engine(tex_file) == "xelatex"


def test_auto_detect_engine_lualatex(tmp_path: Path) -> None:
    """Verify lualatex is detected when luacode is used."""
    tex_file = tmp_path / "luatex_doc.tex"
    tex_file.write_text(
        "\\documentclass{article}\n\\usepackage{luacode}\n\\begin{document}Hello\\end{document}",
        encoding="utf-8",
    )
    assert compile_runner.auto_detect_engine(tex_file) == "lualatex"


def test_auto_detect_engine_pdflatex(tmp_path: Path) -> None:
    """Verify default engine is pdflatex for standard documents."""
    tex_file = tmp_path / "standard_doc.tex"
    tex_file.write_text(
        "\\documentclass{article}\n\\begin{document}Hello\\end{document}",
        encoding="utf-8",
    )
    assert compile_runner.auto_detect_engine(tex_file) == "pdflatex"


# ---------------------------------------------------------------------------
# 4. compile_runner Environment Inspection & CLI Flags
# ---------------------------------------------------------------------------


def test_compile_runner_inspect_environment() -> None:
    """Verify inspect_environment returns required metadata dictionary."""
    env = compile_runner.inspect_environment()
    assert isinstance(env, dict)
    assert "platform" in env
    assert "native_engines" in env
    assert "docker" in env
    assert "syntax_validator" in env
    assert env["syntax_validator"]["available"] is True


def test_compile_runner_check_mode(capsys: pytest.CaptureFixture) -> None:
    """Verify compile_runner main with --check exits with code 0 and displays diagnostics."""
    with patch.object(sys, "argv", ["compile_runner.py", "--check"]):
        ret = compile_runner.main()
        assert ret == 0
        captured = capsys.readouterr()
        assert "LaTeX Compilation Environment Inspection" in captured.out


def test_compile_runner_dry_run_ok(templates_path: Path) -> None:
    """Verify compile_runner with --dry-run-ok exits 0 on valid document without compiler."""
    sample_file = templates_path / "resume-classic-ats.tex"
    with patch("compile_runner.check_binary", return_value=None):
        with patch("compile_runner.is_docker_daemon_running", return_value=False):
            with patch.object(
                sys,
                "argv",
                ["compile_runner.py", "--file", str(sample_file), "--dry-run-ok"],
            ):
                ret = compile_runner.main()
                assert ret == 0


def test_compile_runner_no_compiler_fails_without_dry_run(templates_path: Path) -> None:
    """Verify compile_runner exits 1 without --dry-run-ok when no compiler is present."""
    sample_file = templates_path / "resume-classic-ats.tex"
    with patch("compile_runner.check_binary", return_value=None):
        with patch("compile_runner.is_docker_daemon_running", return_value=False):
            with patch.object(
                sys,
                "argv",
                ["compile_runner.py", "--file", str(sample_file)],
            ):
                ret = compile_runner.main()
                assert ret == 1


def test_compile_runner_json_output(templates_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Verify compile_runner produces valid JSON output with --json."""
    sample_file = templates_path / "resume-classic-ats.tex"
    with patch("compile_runner.check_binary", return_value=None):
        with patch("compile_runner.is_docker_daemon_running", return_value=False):
            with patch.object(
                sys,
                "argv",
                ["compile_runner.py", "--file", str(sample_file), "--dry-run-ok", "--json"],
            ):
                ret = compile_runner.main()
                assert ret == 0
                captured = capsys.readouterr()
                data = json.loads(captured.out)
                assert data["tier"] == 3
                assert data["status"] == "syntax_validated"
                assert "guidance" in data


# ---------------------------------------------------------------------------
# 5. Mocked Compiler Execution & Error Handling
# ---------------------------------------------------------------------------


def test_compile_with_native_success(tmp_path: Path) -> None:
    """Verify compile_with_native runs compiler command and handles success."""
    tex_file = tmp_path / "test.tex"
    tex_file.write_text("\\begin{document}\\end{document}", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "Output written on test.pdf"
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        rc, out = compile_runner.compile_with_native(tex_file, "pdflatex", output_dir)
        assert rc == 0
        assert "Output written" in out
        mock_run.assert_called_once()


def test_compile_with_native_failure(tmp_path: Path) -> None:
    """Verify compile_with_native returns non-zero code on compilation failure."""
    tex_file = tmp_path / "test.tex"
    tex_file.write_text("invalid content", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stdout = "! Undefined control sequence"
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc):
        rc, out = compile_runner.compile_with_native(tex_file, "pdflatex", output_dir)
        assert rc == 1
        assert "Undefined control sequence" in out


def test_compile_with_docker_success(tmp_path: Path) -> None:
    """Verify compile_with_docker issues docker command correctly."""
    tex_file = tmp_path / "test.tex"
    tex_file.write_text("\\begin{document}\\end{document}", encoding="utf-8")
    output_dir = tmp_path / "out"

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "Docker build success"
    mock_proc.stderr = ""

    with patch("compile_runner.check_binary", return_value="/usr/bin/docker"):
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            rc, out = compile_runner.compile_with_docker(tex_file, "pdflatex", output_dir)
            assert rc == 0
            assert "Docker build success" in out
            args, kwargs = mock_run.call_args
            cmd = args[0]
            assert "texlive/texlive:latest" in cmd
            assert "pdflatex" in cmd
