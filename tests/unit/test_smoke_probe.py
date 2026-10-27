"""Unit tests for LiveSmokeProbe and harness-agent smoke command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from harness_agent.cli import main
from harness_agent.core.smoke import LiveSmokeProbe, SmokeProbeResult


def test_smoke_probe_result_model():
    """Verify SmokeProbeResult data structure attributes."""
    res = SmokeProbeResult(
        name="Test Probe",
        command=["python", "--version"],
        exit_code=0,
        passed=True,
        stdout="Python 3.10.0\n",
        stderr="",
        duration_seconds=0.12,
    )
    assert res.name == "Test Probe"
    assert res.exit_code == 0
    assert res.passed is True
    assert res.duration_seconds == 0.12
    assert res.error_message is None


def test_live_smoke_probe_timeout_handling():
    """Verify timeout handling in _execute_subprocess returns failure and duration."""
    probe = LiveSmokeProbe(timeout_seconds=0.01)
    # python -c "import time; time.sleep(1)" will trigger timeout
    res = probe._execute_subprocess(
        name="Timeout Probe",
        cmd=["python", "-c", "import time; time.sleep(1)"],
    )
    code, stdout, stderr, duration, err = res
    assert code == -1
    assert "timed out" in (err or "").lower()


def test_run_cli_help_probe():
    """Verify run_cli_help_probe executes and captures output."""
    probe = LiveSmokeProbe()
    res = probe.run_cli_help_probe()
    assert res.name == "CLI Help Probe"
    assert res.exit_code == 0
    assert res.passed is True


def test_run_cli_check_probe():
    """Verify run_cli_check_probe executes."""
    probe = LiveSmokeProbe()
    res = probe.run_cli_check_probe()
    assert res.name == "CLI Check Probe"
    assert res.exit_code == 0
    assert res.passed is True


def test_run_isolated_init_probe(tmp_path: Path):
    """Verify run_isolated_init_probe creates assets in temporary directory."""
    probe = LiveSmokeProbe()
    res = probe.run_isolated_init_probe(target_dir=tmp_path)
    assert res.name == "Isolated Init Probe"
    assert res.exit_code == 0
    assert res.passed is True


def test_run_all_probes():
    """Verify run_all executes all standard probes."""
    probe = LiveSmokeProbe()
    results = probe.run_all()
    assert len(results) == 3
    assert all(r.passed for r in results)


# Aliases matching alternative naming conventions in sub-specs
test_cli_help_probe = test_run_cli_help_probe
test_isolated_init_probe = test_run_isolated_init_probe
test_run_all_smoke_probes = test_run_all_probes


def test_cli_smoke_command_success():
    """Verify click CLI smoke command in strict mode passes when all probes pass."""
    runner = CliRunner()
    with patch.object(
        LiveSmokeProbe,
        "run_all",
        return_value=[
            SmokeProbeResult(
                name="CLI Help Probe",
                command=["dummy"],
                exit_code=0,
                passed=True,
                stdout="ok",
                stderr="",
                duration_seconds=0.1,
            )
        ],
    ):
        result = runner.invoke(main, ["smoke"])
        assert result.exit_code == 0
        assert "[PASSED] All smoke probes succeeded" in result.output


def test_cli_smoke_command_strict_failure():
    """Verify click CLI smoke command exits with code 1 in strict mode on probe failure."""
    runner = CliRunner()
    with patch.object(
        LiveSmokeProbe,
        "run_all",
        return_value=[
            SmokeProbeResult(
                name="Failing Probe",
                command=["dummy"],
                exit_code=1,
                passed=False,
                stdout="",
                stderr="error message",
                duration_seconds=0.2,
                error_message="Check failed",
            )
        ],
    ):
        result = runner.invoke(main, ["smoke", "--strict"])
        assert result.exit_code == 1
        assert "[FAILED] One or more smoke probes failed" in result.output
        assert "Reason: Check failed" in result.output


def test_cli_smoke_command_lenient_failure():
    """Verify click CLI smoke command exits with code 0 in lenient mode on probe failure."""
    runner = CliRunner()
    with patch.object(
        LiveSmokeProbe,
        "run_all",
        return_value=[
            SmokeProbeResult(
                name="Failing Probe",
                command=["dummy"],
                exit_code=1,
                passed=False,
                stdout="",
                stderr="error message",
                duration_seconds=0.2,
                error_message="Check failed",
            )
        ],
    ):
        result = runner.invoke(main, ["smoke", "--lenient"])
        assert result.exit_code == 0
        assert "[FAILED] One or more smoke probes failed" in result.output
