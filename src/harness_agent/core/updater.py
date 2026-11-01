"""Core Git CLI updater for harness-agent."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

from pydantic import BaseModel


class UpdateResult(BaseModel):
    """Result returned by GitCLIUpdater.update."""

    success: bool
    already_up_to_date: bool = False
    old_commit: str = ""
    new_commit: str = ""
    message: str = ""
    files_changed: int = 0


class GitCLIUpdater:
    """Safely updates harness-agent repository, dependencies, and verifies CLI runtime."""

    def __init__(self, repo_root: Optional[Path] = None) -> None:
        self.repo_root = repo_root or self._detect_repo_root()

    def _detect_repo_root(self) -> Path:
        """Find git root via git rev-parse --show-toplevel or fallback to current dir."""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return Path(res.stdout.strip()).resolve()
        except Exception:
            pass
        return Path.cwd().resolve()

    def _is_git_repository(self) -> bool:
        """Check if self.repo_root is inside a valid git repository."""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(self.repo_root),
            )
            return res.returncode == 0 and res.stdout.strip() == "true"
        except Exception:
            return False

    def check_clean_worktree(self) -> Tuple[bool, str]:
        """Check if worktree is clean via git status --porcelain."""
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(self.repo_root),
            )
            if res.returncode != 0:
                err = res.stderr.strip() or "Failed to run git status"
                return False, err
            status_output = res.stdout.strip()
            if status_output:
                return False, status_output
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def get_current_commit(self) -> str:
        """Get HEAD commit SHA (short 7-char)."""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--short=7", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(self.repo_root),
            )
            if res.returncode == 0:
                return res.stdout.strip()
        except Exception:
            pass
        return ""

    def get_current_branch(self) -> str:
        """Get active branch name."""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(self.repo_root),
            )
            if res.returncode == 0:
                return res.stdout.strip()
        except Exception:
            pass
        return "main"

    def run_git_pull(
        self, remote: str = "origin", branch: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Execute git pull <remote> <branch> safely."""
        target_branch = branch or self.get_current_branch()
        cmd = ["git", "pull", remote, target_branch]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                cwd=str(self.repo_root),
            )
            out = res.stdout + ("\n" + res.stderr if res.stderr else "")
            return (res.returncode == 0, out.strip())
        except Exception as exc:
            return (False, str(exc))

    def resync_editable_install(self) -> Tuple[bool, str]:
        """Execute sys.executable -m pip install -e . --no-deps."""
        cmd = [sys.executable, "-m", "pip", "install", "-e", ".", "--no-deps"]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                cwd=str(self.repo_root),
            )
            out = res.stdout + ("\n" + res.stderr if res.stderr else "")
            return (res.returncode == 0, out.strip())
        except Exception as exc:
            return (False, str(exc))

    def run_smoke_verification(self) -> Tuple[bool, str]:
        """Execute harness-agent check or quick CLI probe to verify runtime integrity."""
        cmd = [sys.executable, "-m", "harness_agent.cli", "check"]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                cwd=str(self.repo_root),
            )
            out = res.stdout + ("\n" + res.stderr if res.stderr else "")
            return (res.returncode == 0, out.strip())
        except Exception as exc:
            return (False, str(exc))

    def update(
        self,
        remote: str = "origin",
        branch: Optional[str] = None,
        force: bool = False,
        skip_pip: bool = False,
    ) -> UpdateResult:
        """Complete orchestrated update workflow."""
        if not self._is_git_repository():
            return UpdateResult(
                success=False,
                message="[ERROR] Not in a git repository.",
            )

        old_commit = self.get_current_commit()

        # Check clean worktree
        is_clean, dirty_info = self.check_clean_worktree()
        if not is_clean and not force:
            return UpdateResult(
                success=False,
                old_commit=old_commit,
                message=(
                    "Aborted: Working directory has uncommitted changes. "
                    "Please commit or stash before updating."
                ),
            )

        # Pull from remote
        pull_success, pull_output = self.run_git_pull(remote=remote, branch=branch)
        if not pull_success:
            return UpdateResult(
                success=False,
                old_commit=old_commit,
                message=f"[ERROR] Failed to pull from remote: {pull_output}",
            )

        is_already_up_to_date = "already up to date" in pull_output.lower()
        new_commit = self.get_current_commit()

        if is_already_up_to_date and not force:
            self.run_smoke_verification()
            return UpdateResult(
                success=True,
                already_up_to_date=True,
                old_commit=old_commit,
                new_commit=new_commit,
                message="Already up to date. CLI is current.",
            )

        # Sync pip editable install
        if not skip_pip:
            pip_success, pip_out = self.resync_editable_install()
            if not pip_success:
                return UpdateResult(
                    success=False,
                    old_commit=old_commit,
                    new_commit=new_commit,
                    message=f"[ERROR] Failed to re-sync editable package: {pip_out}",
                )

        # Run smoke probe
        smoke_success, smoke_out = self.run_smoke_verification()
        if not smoke_success:
            return UpdateResult(
                success=False,
                old_commit=old_commit,
                new_commit=new_commit,
                message=f"[ERROR] Post-update smoke verification failed: {smoke_out}",
            )

        return UpdateResult(
            success=True,
            already_up_to_date=is_already_up_to_date,
            old_commit=old_commit,
            new_commit=new_commit,
            message=f"Successfully updated harness-agent ({old_commit} -> {new_commit}).",
        )
