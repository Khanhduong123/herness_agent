"""Interactive worker agent dispatcher using Herdr multiplexer."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple


class HerdrDispatcher:
    """Automates visible, interactive worker agent dispatch in Herdr multiplexer panes."""

    @staticmethod
    def get_worker_name(task_id: str) -> str:
        """Return canonical worker agent name for task ID."""
        return task_id if task_id.startswith("worker_") else f"worker_{task_id}"

    @staticmethod
    def get_branch_name(task_id: str) -> str:
        """Return canonical git branch name for task ID."""
        return task_id if task_id.startswith("agent/") else f"agent/{task_id}"

    @staticmethod
    def is_herdr_available(executable: str = "herdr") -> bool:
        """Check if herdr CLI is available in PATH.

        Args:
            executable: Herdr executable binary name or path.

        Returns:
            bool: True if herdr is installed and on PATH, False otherwise.
        """
        return shutil.which(executable) is not None

    @classmethod
    def create_agent_worktree(
        cls,
        task_id: str,
        base_ref: Optional[str] = None,
        executable: str = "herdr",
        repo_root: Optional[Path] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """Run 'herdr worktree create --branch agent/<task_id>' and extract root pane_id.

        Args:
            task_id: Task identifier for the worktree branch.
            base_ref: Optional base git reference to branch from.
            executable: Herdr executable binary name or path.
            repo_root: Optional repository root path.

        Returns:
            Tuple[bool, str, Optional[str]]: (success, message_or_path, pane_id)
        """
        branch = cls.get_branch_name(task_id)
        cmd = [executable, "worktree", "create", "--branch", branch]
        if base_ref:
            cmd.extend(["--base", base_ref])

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return False, f"Executable '{executable}' not found", None
        except Exception as exc:
            return False, str(exc), None

        if proc.returncode != 0:
            err = (
                proc.stderr.strip()
                or proc.stdout.strip()
                or f"Process exited with code {proc.returncode}"
            )
            return False, err, None

        stdout = proc.stdout.strip()
        pane_id: Optional[str] = None
        path: str = ""

        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                res = data.get("result", data)
                if isinstance(res, dict):
                    path = (
                        res.get("path")
                        or res.get("checkout_path")
                        or res.get("workspace", {}).get("worktree", {}).get("checkout_path")
                        or res.get("worktree", {}).get("path")
                        or ""
                    )
                    pane_id = (
                        res.get("pane_id")
                        or res.get("pane", {}).get("pane_id")
                        or res.get("workspace", {}).get("pane_id")
                        or res.get("workspace", {}).get("active_pane_id")
                    )
                    workspace_id = res.get("workspace_id") or res.get("workspace", {}).get(
                        "workspace_id"
                    )
                    if not pane_id and workspace_id:
                        pane_id = f"{workspace_id}:p1"
        except Exception:
            pass

        if not pane_id:
            m = re.search(r"\b([a-zA-Z0-9_\-]+:p\d+)\b", stdout)
            if m:
                pane_id = m.group(1)

        if not path:
            path = stdout

        if path:
            candidate_paths = [Path(path)]
            clean_task_id = task_id.replace("agent/", "").replace("worker_", "")
            candidate_paths.append(Path(".worktrees") / "agent" / clean_task_id)
            if repo_root:
                candidate_paths.append(repo_root / ".worktrees" / "agent" / clean_task_id)
                if not Path(path).is_absolute():
                    candidate_paths.append(repo_root / path)

            for cp in candidate_paths:
                if cp.exists() and cp.is_dir():
                    cls.setup_worktree_env(cp, repo_root=repo_root)
                    break

        return True, path, pane_id

    @classmethod
    def start_agent(
        cls,
        task_id: str,
        pane_id: str,
        kind: str = "agy",
        dangerously_skip_permissions: bool = True,
        executable: str = "herdr",
    ) -> Tuple[bool, str]:
        """Run 'herdr agent start worker_<task_id> --kind <kind> --pane <pane_id>'.

        Args:
            task_id: Task identifier.
            pane_id: Pane ID where the interactive agent will run.
            kind: Agent kind (default: 'agy').
            dangerously_skip_permissions: Auto-approve permissions if True.
            executable: Herdr executable binary name or path.

        Returns:
            Tuple[bool, str]: (success, output_or_error_message)
        """
        worker_name = cls.get_worker_name(task_id)
        cmd = [executable, "agent", "start", worker_name, "--kind", kind, "--pane", pane_id]
        if dangerously_skip_permissions:
            cmd.extend(["--", "--dangerously-skip-permissions"])

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return False, f"Executable '{executable}' not found"
        except Exception as exc:
            return False, str(exc)

        if proc.returncode != 0:
            err = (
                proc.stderr.strip()
                or proc.stdout.strip()
                or f"Process exited with code {proc.returncode}"
            )
            return False, err

        return True, proc.stdout.strip()

    @classmethod
    def prompt_agent(
        cls,
        task_id: str,
        prompt: str,
        wait: bool = False,
        executable: str = "herdr",
    ) -> Tuple[bool, str]:
        """Run 'herdr agent prompt worker_<task_id> "<prompt>"'.

        Args:
            task_id: Task identifier.
            prompt: Prompt instruction text to send to the worker agent.
            wait: Wait for first matching settled state if True.
            executable: Herdr executable binary name or path.

        Returns:
            Tuple[bool, str]: (success, output_or_error_message)
        """
        worker_name = cls.get_worker_name(task_id)
        cmd = [executable, "agent", "prompt", worker_name, prompt]
        if wait:
            cmd.append("--wait")

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return False, f"Executable '{executable}' not found"
        except Exception as exc:
            return False, str(exc)

        if proc.returncode != 0:
            err = (
                proc.stderr.strip()
                or proc.stdout.strip()
                or f"Process exited with code {proc.returncode}"
            )
            return False, err

        return True, proc.stdout.strip()

    @classmethod
    def dispatch_interactive_critics(
        cls,
        base_ref: str = "main",
        task_id: Optional[str] = None,
        executable: str = "herdr",
        repo_root: Optional[Path] = None,
    ) -> Tuple[bool, str]:
        """Launch an interactive Adversarial Critic inspection session in a Herdr split pane.

        Args:
            base_ref: Base git reference to compute diff against (default: main).
            task_id: Optional task identifier for naming the critic agent.
            executable: Herdr executable binary name or path.
            repo_root: Optional repository root path.

        Returns:
            Tuple[bool, str]: (success, status_or_error_message)
        """
        if not cls.is_herdr_available(executable=executable):
            return False, f"Herdr CLI '{executable}' is not installed or not in PATH"

        root = repo_root or Path.cwd()

        # 1. Retrieve git diff against base_ref
        diff_text = ""
        try:
            diff_proc = subprocess.run(
                ["git", "diff", f"{base_ref}...HEAD"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
            if diff_proc.returncode == 0 and diff_proc.stdout.strip():
                diff_text = diff_proc.stdout.strip()
            else:
                diff_proc2 = subprocess.run(
                    ["git", "diff", base_ref],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if diff_proc2.returncode == 0:
                    diff_text = diff_proc2.stdout.strip()
        except Exception as exc:
            return False, f"Failed to retrieve git diff against {base_ref}: {exc}"

        from harness_agent.evaluation.critics import sanitize_and_truncate_diff

        sanitized_diff, _, _ = sanitize_and_truncate_diff(diff_text)
        if not sanitized_diff:
            sanitized_diff = "[No diff changes detected against base branch]"

        # 2. Create a dedicated split pane in Herdr
        split_cmd = [executable, "pane", "split", "--direction", "right", "--no-focus"]
        try:
            proc = subprocess.run(
                split_cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                fallback_cmd = [executable, "pane", "split"]
                proc = subprocess.run(
                    fallback_cmd,
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    check=False,
                )
        except FileNotFoundError:
            return False, f"Executable '{executable}' not found"
        except Exception as exc:
            return False, f"Failed to create Herdr split pane: {exc}"

        if proc.returncode != 0:
            err = (
                proc.stderr.strip()
                or proc.stdout.strip()
                or f"Process exited with code {proc.returncode}"
            )
            return False, f"Failed to create Herdr split pane: {err}"

        stdout = proc.stdout.strip()
        pane_id: Optional[str] = None
        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                res = data.get("result", data)
                if isinstance(res, dict):
                    pane_id = (
                        res.get("pane_id")
                        or res.get("pane", {}).get("pane_id")
                        or res.get("workspace", {}).get("pane_id")
                        or res.get("workspace", {}).get("active_pane_id")
                    )
        except Exception:
            pass

        if not pane_id:
            m = re.search(r"\b([a-zA-Z0-9_\-]+:p\d+)\b", stdout)
            if m:
                pane_id = m.group(1)
            else:
                m2 = re.search(r"\b(pane_[a-zA-Z0-9_\-]+)\b", stdout)
                if m2:
                    pane_id = m2.group(1)

        if not pane_id:
            return False, f"Could not extract pane ID from Herdr split pane output: {stdout}"

        # 3. Launch interactive Critic agent in the split pane
        critic_name = (
            f"critic_{task_id.replace('agent/', '').replace('worker_', '')}"
            if task_id
            else f"critic_review_{int(time.time())}"
        )
        start_cmd = [
            executable,
            "agent",
            "start",
            critic_name,
            "--kind",
            "agy",
            "--pane",
            pane_id,
            "--",
            "--dangerously-skip-permissions",
        ]
        try:
            start_proc = subprocess.run(
                start_cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            return False, f"Failed to start critic agent in pane {pane_id}: {exc}"

        if start_proc.returncode != 0:
            err = (
                start_proc.stderr.strip()
                or start_proc.stdout.strip()
                or f"Process exited with code {start_proc.returncode}"
            )
            return False, f"Failed to start critic agent: {err}"

        # 4. Feed sanitized diff with role anchor
        role_anchor = (
            "[SYSTEM CONTEXT: You are an Adversarial Critic Agent operating strictly in "
            "READ-ONLY mode. You CANNOT modify code or dispatch agents. You only evaluate "
            "git diffs and code against specifications.]"
        )
        prompt_content = (
            f"{role_anchor}\n\n"
            f"# Adversarial Critic Inspection (Target Base: {base_ref})\n\n"
            f"Review the following git diff against {base_ref} strictly for:\n"
            f"1. Security vulnerabilities (SQLi, command injection, secrets, unsafe eval)\n"
            f"2. Algorithmic complexity and bottlenecks (nested O(N^2) loops, leaks)\n"
            f"3. Functional correctness, type safety, and acceptance criteria\n\n"
            f"```diff\n"
            f"{sanitized_diff}\n"
            f"```\n\n"
            f"Output STATUS: APPROVED if all criteria pass, or STATUS: REJECTED with defects."
        )

        prompt_cmd = [executable, "agent", "prompt", critic_name, prompt_content]
        try:
            prompt_proc = subprocess.run(
                prompt_cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            return False, f"Failed to prompt critic agent: {exc}"

        if prompt_proc.returncode != 0:
            err = (
                prompt_proc.stderr.strip()
                or prompt_proc.stdout.strip()
                or f"Process exited with code {prompt_proc.returncode}"
            )
            return False, f"Failed to prompt critic agent: {err}"

        return (
            True,
            f"Dispatched interactive critic inspection agent '{critic_name}' in pane '{pane_id}'",
        )

    @classmethod
    def wait_for_task(
        cls,
        task_id: str,
        timeout_seconds: int = 600,
        poll_interval: float = 2.0,
        status_dir: Optional[Path] = None,
        executable: str = "herdr",
    ) -> Tuple[bool, str]:
        """Block locally in Python until completion flag file appears or timeout expires.

        Args:
            task_id: Task identifier.
            timeout_seconds: Maximum seconds to wait.
            poll_interval: Seconds between poll checks.
            status_dir: Optional path to status directory. Defaults to .ai/status.
            executable: Herdr executable binary name or path.

        Returns:
            Tuple[bool, str]: (success, message_or_content)
        """
        sdir = status_dir or Path(".ai/status")
        clean_task_id = task_id.replace("agent/", "").replace("worker_", "")
        flag_candidates = [
            sdir / f"{task_id}.complete",
            sdir / f"{clean_task_id}.complete",
        ]

        start_time = time.time()
        while True:
            for flag in flag_candidates:
                if flag.is_file():
                    try:
                        content = flag.read_text(encoding="utf-8").strip()
                        return True, content or "[WORKER_COMPLETED]"
                    except Exception:
                        pass

            elapsed = time.time() - start_time
            if elapsed >= timeout_seconds:
                return False, f"Task {task_id} timed out after {timeout_seconds}s"

            sleep_time = min(poll_interval, max(0.01, timeout_seconds - elapsed))
            time.sleep(sleep_time)

    @classmethod
    def create_feature_branch(
        cls,
        feature_name: str,
        base_branch: str = "main",
        repo_root: Optional[Path] = None,
    ) -> Tuple[bool, str]:
        """Create and checkout a new feature branch from base_branch.

        Args:
            feature_name: Feature name (prefixed with feat/ if not already).
            base_branch: Base branch name (default: main).
            repo_root: Optional repository root path.

        Returns:
            Tuple[bool, str]: (success, message)
        """
        try:
            status_proc = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(repo_root) if repo_root else None,
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            return False, str(exc)

        if status_proc.returncode != 0:
            err = status_proc.stderr.strip() or status_proc.stdout.strip()
            return False, f"Failed to check git status: {err}"

        if status_proc.stdout.strip():
            return (
                False,
                "Working tree is dirty. Stash or commit changes before creating feature branch.",
            )

        branch_name = feature_name if feature_name.startswith("feat/") else f"feat/{feature_name}"
        try:
            checkout_proc = subprocess.run(
                ["git", "checkout", "-b", branch_name, base_branch],
                cwd=str(repo_root) if repo_root else None,
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            return False, str(exc)

        if checkout_proc.returncode != 0:
            err = checkout_proc.stderr.strip() or checkout_proc.stdout.strip()
            return False, f"Failed to create feature branch {branch_name}: {err}"

        return True, f"Created and checked out branch '{branch_name}' from '{base_branch}'"

    @classmethod
    def setup_worktree_env(
        cls,
        worktree_path: Path,
        repo_root: Optional[Path] = None,
    ) -> List[str]:
        """Copy environment and configuration files from repo root into worktree.

        Args:
            worktree_path: Target worktree directory path.
            repo_root: Optional repository root path. Defaults to cwd.

        Returns:
            List[str]: Names of copied files.
        """
        root = repo_root or Path.cwd()
        worktree_path = Path(worktree_path)
        worktree_path.mkdir(parents=True, exist_ok=True)
        env_files = [".env", ".env.test", ".env.local", ".env.example", ".flake8"]
        copied: List[str] = []
        for filename in env_files:
            src = root / filename
            if src.is_file():
                dest = worktree_path / filename
                if src.resolve() != dest.resolve():
                    shutil.copy2(src, dest)
                    copied.append(filename)
        return copied

    @classmethod
    def stop_agent(
        cls,
        task_id: str,
        executable: str = "herdr",
    ) -> Tuple[bool, str]:
        """Stop worker agent in Herdr pane.

        Args:
            task_id: Task identifier.
            executable: Herdr executable binary name or path.

        Returns:
            Tuple[bool, str]: (success, message)
        """
        worker_name = cls.get_worker_name(task_id)
        cmd = [executable, "agent", "stop", worker_name]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return False, f"Executable '{executable}' not found"
        except Exception as exc:
            return False, str(exc)

        if proc.returncode != 0:
            err = (
                proc.stderr.strip()
                or proc.stdout.strip()
                or f"Process exited with code {proc.returncode}"
            )
            return False, err

        return True, proc.stdout.strip() or f"Agent '{worker_name}' stopped successfully"

    @classmethod
    def cleanup_worktree(
        cls,
        task_id: str,
        worktree_path: Optional[str] = None,
        force: bool = True,
        repo_root: Optional[Path] = None,
        executable: str = "herdr",
    ) -> Tuple[bool, str]:
        """Stop worker agent, wait 1s, and remove git worktree.

        Args:
            task_id: Task identifier.
            worktree_path: Optional explicit worktree path.
            force: Force removal if True.
            repo_root: Optional repository root path.
            executable: Herdr executable binary name or path.

        Returns:
            Tuple[bool, str]: (success, message)
        """
        cls.stop_agent(task_id, executable=executable)
        time.sleep(1.0)

        clean_task_id = task_id.replace("agent/", "").replace("worker_", "")
        if worktree_path:
            target = worktree_path
        else:
            wt_rel = Path(".worktrees") / "agent" / clean_task_id
            target = str((repo_root / wt_rel) if repo_root else wt_rel)

        cmd = ["git", "worktree", "remove"]
        if force:
            cmd.append("--force")
        cmd.append(target)

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(repo_root) if repo_root else None,
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            return False, str(exc)

        if proc.returncode != 0:
            err = (
                proc.stderr.strip()
                or proc.stdout.strip()
                or f"git worktree remove exited with {proc.returncode}"
            )
            return False, err

        return True, f"Cleaned up worktree for task {task_id}"

    @classmethod
    def merge_worktree_to_feature(
        cls,
        task_id: str,
        target_branch: str,
        no_ff: bool = True,
        repo_root: Optional[Path] = None,
        executable: str = "herdr",
    ) -> Tuple[bool, str]:
        """Stop worker agent, switch to target_branch, merge subtask branch, and cleanup.

        Args:
            task_id: Task identifier.
            target_branch: Feature branch to merge into.
            no_ff: Use --no-ff flag if True.
            repo_root: Optional repository root path.
            executable: Herdr executable binary name or path.

        Returns:
            Tuple[bool, str]: (success, message)
        """
        cls.stop_agent(task_id, executable=executable)

        branch_name = cls.get_branch_name(task_id)
        clean_task_id = task_id.replace("agent/", "").replace("worker_", "")

        try:
            checkout_proc = subprocess.run(
                ["git", "checkout", target_branch],
                cwd=str(repo_root) if repo_root else None,
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            return False, str(exc)

        if checkout_proc.returncode != 0:
            err = checkout_proc.stderr.strip() or checkout_proc.stdout.strip()
            return False, f"Failed to checkout {target_branch}: {err}"

        commit_msg = f"feat({clean_task_id}): integrate subtask into {target_branch}"
        merge_cmd = ["git", "merge"]
        if no_ff:
            merge_cmd.append("--no-ff")
        merge_cmd.extend([branch_name, "-m", commit_msg])

        try:
            merge_proc = subprocess.run(
                merge_cmd,
                cwd=str(repo_root) if repo_root else None,
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            return False, str(exc)

        if merge_proc.returncode != 0:
            err = merge_proc.stderr.strip() or merge_proc.stdout.strip()
            return False, f"Failed to merge {branch_name} into {target_branch}: {err}"

        cls.cleanup_worktree(task_id, repo_root=repo_root, executable=executable)

        del_proc = subprocess.run(
            ["git", "branch", "-d", branch_name],
            cwd=str(repo_root) if repo_root else None,
            capture_output=True,
            text=True,
            check=False,
        )
        if del_proc.returncode != 0:
            subprocess.run(
                ["git", "branch", "-D", branch_name],
                cwd=str(repo_root) if repo_root else None,
                capture_output=True,
                text=True,
                check=False,
            )

        return (
            True,
            f"Successfully merged {branch_name} into {target_branch} and cleaned up worktree",
        )

    @classmethod
    def abort_task(
        cls,
        task_id: str,
        reason: str = "",
        repo_root: Optional[Path] = None,
        executable: str = "herdr",
    ) -> Tuple[bool, str]:
        """Abort subtask, archive failure diagnostic diff, stop agent, and remove worktree.

        Args:
            task_id: Task identifier.
            reason: Explanation for task abort.
            repo_root: Optional repository root path.
            executable: Herdr executable binary name or path.

        Returns:
            Tuple[bool, str]: (success, message)
        """
        root = repo_root or Path.cwd()
        failures_dir = root / ".ai" / "failures"
        failures_dir.mkdir(parents=True, exist_ok=True)
        clean_task_id = task_id.replace("agent/", "").replace("worker_", "")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = failures_dir / f"{clean_task_id}_{timestamp}.log"

        branch_name = cls.get_branch_name(task_id)
        wt_path = root / ".worktrees" / "agent" / clean_task_id
        diff_cwd = wt_path if wt_path.exists() else root

        diff_text = ""
        try:
            diff_proc = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=str(diff_cwd),
                capture_output=True,
                text=True,
                check=False,
            )
            if diff_proc.returncode == 0:
                diff_text = diff_proc.stdout.strip()
        except Exception:
            diff_text = ""

        log_content = (
            f"Task ID: {task_id}\n"
            f"Timestamp: {timestamp}\n"
            f"Reason: {reason or 'Aborted by user/orchestrator'}\n\n"
            f"--- GIT DIFF HEAD ---\n"
            f"{diff_text}\n"
        )
        try:
            log_file.write_text(log_content, encoding="utf-8")
        except Exception as exc:
            return False, f"Failed to archive failure log: {exc}"

        cls.stop_agent(task_id, executable=executable)
        cls.cleanup_worktree(task_id, repo_root=repo_root, executable=executable)

        subprocess.run(
            ["git", "branch", "-D", branch_name],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )

        return True, f"Task {task_id} aborted. Failure log archived to {log_file}"


# Module-level aliases
wait_for_task = HerdrDispatcher.wait_for_task
create_feature_branch = HerdrDispatcher.create_feature_branch
merge_worktree_to_feature = HerdrDispatcher.merge_worktree_to_feature
stop_agent = HerdrDispatcher.stop_agent
cleanup_worktree = HerdrDispatcher.cleanup_worktree
setup_worktree_env = HerdrDispatcher.setup_worktree_env
abort_task = HerdrDispatcher.abort_task
dispatch_interactive_critics = HerdrDispatcher.dispatch_interactive_critics

__all__ = [
    "HerdrDispatcher",
    "abort_task",
    "cleanup_worktree",
    "create_feature_branch",
    "dispatch_interactive_critics",
    "merge_worktree_to_feature",
    "setup_worktree_env",
    "stop_agent",
    "wait_for_task",
]
