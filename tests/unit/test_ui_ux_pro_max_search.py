import json
import subprocess
import sys
from pathlib import Path

# Paths
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = REPO_ROOT / ".agents" / "skills" / "ui-ux-pro-max" / "scripts" / "search.py"


def run_search_cli(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Helper to execute search.py using the current Python executable."""
    cmd = [sys.executable, str(SCRIPT_PATH)] + args
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_search_domain_product():
    """TC-01: Verify domain search for product returns matches."""
    result = run_search_cli(["saas", "--domain", "product"])
    assert result.returncode == 0, f"Error: {result.stderr}"
    assert "## UI Pro Max Search Results" in result.stdout
    assert "SaaS (General)" in result.stdout
    assert "Primary Style Recommendation:" in result.stdout


def test_design_system_generation():
    """TC-02: Verify design system generation outputs key sections."""
    result = run_search_cli(["ai terminal", "--design-system"])
    assert result.returncode == 0, f"Error: {result.stderr}"
    stdout = result.stdout
    assert "RECOMMENDED DESIGN SYSTEM" in stdout
    assert "PRIMARY" in stdout.upper()
    assert "BACKGROUND" in stdout.upper()
    assert "TYPOGRAPHY" in stdout.upper()


def test_stack_search_react_native():
    """TC-03: Verify stack search with react-native returns recommendations."""
    result = run_search_cli(["button", "--stack", "react-native"])
    assert result.returncode == 0, f"Error: {result.stderr}"
    assert "## UI Pro Max Stack Guidelines" in result.stdout
    assert "react-native" in result.stdout
    assert "accessibilityRole" in result.stdout or "BackHandler" in result.stdout


def test_search_from_arbitrary_cwd(tmp_path: Path):
    """TC-04 & Edge Case 1: Execute search from arbitrary working directory."""
    result = run_search_cli(["minimalism", "--domain", "style"], cwd=tmp_path)
    assert result.returncode == 0, f"Error: {result.stderr}"
    assert "## UI Pro Max Search Results" in result.stdout
    assert "Minimalism & Swiss Style" in result.stdout


def test_empty_query_zero_matches(tmp_path: Path):
    """Edge Case 2: Query yielding zero matches gracefully reports 0 results in JSON and text."""
    # Text mode
    result = run_search_cli(["xyznonexistentquery12345", "--domain", "product"], cwd=tmp_path)
    assert result.returncode == 0
    assert "Found: 0 results" in result.stdout or "No matches" in result.stdout

    # JSON mode
    json_result = run_search_cli(
        ["xyznonexistentquery12345", "--domain", "product", "--json"], cwd=tmp_path
    )
    assert json_result.returncode == 0
    data = json.loads(json_result.stdout)
    assert data["count"] == 0
    assert len(data["results"]) == 0


def test_design_system_dials_defaults(tmp_path: Path):
    """Edge Case 4: Missing optional dial parameters defaults gracefully."""
    result = run_search_cli(["fintech mobile", "--design-system"], cwd=tmp_path)
    assert result.returncode == 0
    assert "RECOMMENDED DESIGN SYSTEM" in result.stdout
