"""Interactive worker agent dispatcher using Herdr multiplexer."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Optional, Tuple


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
    ) -> Tuple[bool, str, Optional[str]]:
        """Run 'herdr worktree create --branch agent/<task_id>' and extract root pane_id.

        Args:
            task_id: Task identifier for the worktree branch.
            base_ref: Optional base git reference to branch from.
            executable: Herdr executable binary name or path.

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
