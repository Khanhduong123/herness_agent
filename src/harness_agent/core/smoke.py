"""Live smoke probe engine for process verification without in-process mocks."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel


class SmokeProbeResult(BaseModel):
    """Result of a smoke probe execution."""

    name: str
    command: List[str]
    exit_code: int
    passed: bool
    stdout: str
    stderr: str
    duration_seconds: float
    error_message: Optional[str] = None


class LiveSmokeProbe:
    """Executes live out-of-process CLI and runtime smoke probes."""

    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds

    def _execute_subprocess(
        self,
        name: str,
        cmd: List[str],
        cwd: Optional[Path] = None,
        env: Optional[dict] = None,
    ) -> tuple[int, str, str, float, Optional[str]]:
        start_time = time.perf_counter()
        current_env = os.environ.copy()
        if env:
            current_env.update(env)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                cwd=str(cwd) if cwd else None,
                env=current_env,
                check=False,
            )
            duration = time.perf_counter() - start_time
            return proc.returncode, proc.stdout, proc.stderr, duration, None
        except subprocess.TimeoutExpired as exc:
            duration = time.perf_counter() - start_time
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            return -1, stdout, stderr, duration, f"Command timed out after {self.timeout_seconds}s"
        except Exception as exc:
            duration = time.perf_counter() - start_time
            return -1, "", str(exc), duration, f"Execution failed: {exc}"

    def run_cli_help_probe(self) -> SmokeProbeResult:
        """Run CLI --help probe and verify exit 0 and Harness Agent banner."""
        cmd = [sys.executable, "-m", "harness_agent", "--help"]
        code, stdout, stderr, duration, err = self._execute_subprocess(
            name="CLI Help Probe",
            cmd=cmd,
        )
        passed = code == 0 and "harness" in stdout.lower() and err is None
        if code == 0 and not passed and err is None:
            err = "Expected 'harness' in CLI help output"

        return SmokeProbeResult(
            name="CLI Help Probe",
            command=cmd,
            exit_code=code,
            passed=passed,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
            error_message=err,
        )

    def run_cli_check_probe(self) -> SmokeProbeResult:
        """Run CLI check probe."""
        cmd = [sys.executable, "-m", "harness_agent", "check"]
        code, stdout, stderr, duration, err = self._execute_subprocess(
            name="CLI Check Probe",
            cmd=cmd,
        )
        passed = code == 0 and err is None
        if code != 0 and err is None:
            err = f"CLI check returned exit code {code}"

        return SmokeProbeResult(
            name="CLI Check Probe",
            command=cmd,
            exit_code=code,
            passed=passed,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
            error_message=err,
        )

    def run_isolated_init_probe(self, target_dir: Optional[Path] = None) -> SmokeProbeResult:
        """Spawn isolated temporary directory and run init probe."""
        cmd_name = "Isolated Init Probe"
        if target_dir is not None:
            cmd = [sys.executable, "-m", "harness_agent", "init", str(target_dir)]
            code, stdout, stderr, duration, err = self._execute_subprocess(
                name=cmd_name,
                cmd=cmd,
            )
            has_assets = (target_dir / ".ai").exists() or (target_dir / "AGENTS.md").exists()
            passed = code == 0 and has_assets and err is None
            if code == 0 and not has_assets and err is None:
                err = "Target directory did not contain expected harness assets after init"

            return SmokeProbeResult(
                name=cmd_name,
                command=cmd,
                exit_code=code,
                passed=passed,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=duration,
                error_message=err,
            )

        with tempfile.TemporaryDirectory() as tmp_path_str:
            tmp_path = Path(tmp_path_str)
            cmd = [sys.executable, "-m", "harness_agent", "init", str(tmp_path)]
            code, stdout, stderr, duration, err = self._execute_subprocess(
                name=cmd_name,
                cmd=cmd,
            )
            has_assets = (tmp_path / ".ai").exists() or (tmp_path / "AGENTS.md").exists()
            passed = code == 0 and has_assets and err is None
            if code == 0 and not has_assets and err is None:
                err = "Temporary directory did not contain expected harness assets after init"

            return SmokeProbeResult(
                name=cmd_name,
                command=cmd,
                exit_code=code,
                passed=passed,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=duration,
                error_message=err,
            )

    def run_all(self) -> List[SmokeProbeResult]:
        """Execute all smoke probes and return results list."""
        return [
            self.run_cli_help_probe(),
            self.run_cli_check_probe(),
            self.run_isolated_init_probe(),
        ]
