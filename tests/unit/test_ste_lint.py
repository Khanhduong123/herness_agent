import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / ".agents"
    / "skills"
    / "sdlc-technical-documentation"
    / "scripts"
    / "ste-lint.py"
)


@pytest.fixture(scope="module")
def ste_lint_module():
    """Dynamically load ste-lint.py as a module for unit testing its functions."""
    assert SCRIPT_PATH.exists(), f"Linter script not found at {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("ste_lint", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ste_lint_selftest(ste_lint_module):
    """Test 1: Execute the built-in selftest() method from ste-lint.py and assert it passes."""
    ste_lint_module.selftest()


def test_ste_lint_clean_text(ste_lint_module):
    """Test 2: Lint valid STE sentences and assert 0 findings and exit code 0."""
    clean_sample = "Open the valve. Read the pressure. The agent starts the service."
    findings, words = ste_lint_module.lint(clean_sample)
    assert findings == []
    assert words > 0
    # Also verify exit code calculation logic via main() simulation or hard count
    hard_count = sum(1 for f in findings if f["level"] == "advisory-free")
    assert hard_count == 0


def test_ste_lint_structural_violations(ste_lint_module):
    """Test 3: Lint text with semicolons, marketing adjectives, or soft phrasal verbs."""
    violating_sample = "The cutting-edge agent spins up; it works seamlessly."
    findings, _ = ste_lint_module.lint(violating_sample)

    rules_flagged = {f["rule"] for f in findings}
    assert "semicolon" in rules_flagged
    assert "marketing-adjective" in rules_flagged
    assert "phrasal-verb" in rules_flagged

    hard_findings = [f for f in findings if f["level"] == "advisory-free"]
    assert len(hard_findings) >= 3


def test_ste_lint_cli_execution():
    """Test 4: Run the script via subprocess.run([sys.executable, script, '--selftest'])."""
    assert SCRIPT_PATH.exists(), f"Linter script not found at {SCRIPT_PATH}"
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--selftest"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "selftest OK" in result.stdout


def test_ste_lint_empty_input(ste_lint_module):
    """Test 5: Lint empty string or whitespace and assert graceful 0 findings."""
    for empty_val in ["", "   ", "\n\t\n"]:
        findings, words = ste_lint_module.lint(empty_val)
        assert findings == []
        assert words == 0
