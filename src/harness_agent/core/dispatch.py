"""Interactive worker agent dispatcher using Herdr multiplexer."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from harness_agent.core.models import ROLE_DEFAULT_SKILLS, ROLE_TOOL_ALLOWLIST, AgentRole
from harness_agent.core.token_logger import TokenLogger, get_active_model

logger = logging.getLogger(__name__)


def verify_and_load_agents_rule(
    root_path: Union[str, Path],
    max_retries: int = 3,
    base_delay: float = 0.5,
) -> str:
    """Verifies AGENTS.md existence with exponential retry and loads system instructions.

    Args:
        root_path (Union[str, Path]): Root repository directory path.
        max_retries (int): Maximum number of retry attempts before failure.
        base_delay (float): Initial backoff delay in seconds.

    Returns:
        str: Contents of AGENTS.md ready for direct system prompt injection.

    Raises:
        RuntimeError: If AGENTS.md cannot be read after maximum retries.
        ValueError: If AGENTS.md is empty.
    """
    resolved_root = Path(root_path).resolve()
    target_file = resolved_root / "AGENTS.md"

    for attempt in range(max_retries):
        try:
            if target_file.is_file():
                content = target_file.read_text(encoding="utf-8")
                if not content.strip():
                    raise ValueError("AGENTS.md is empty")
                return content
            else:
                logger.warning(
                    "Pre-flight verification attempt %d/%d: %s not found",
                    attempt + 1,
                    max_retries,
                    target_file,
                )
        except ValueError:
            raise
        except (PermissionError, OSError) as exc:
            logger.warning(
                "Pre-flight verification attempt %d/%d: Error reading %s: %s",
                attempt + 1,
                max_retries,
                target_file,
                exc,
            )

        if attempt < max_retries - 1:
            delay = base_delay * (2**attempt)
            time.sleep(delay)

    raise RuntimeError("Pre-flight bootstrap failed: AGENTS.md not accessible after retries")


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
    def trust_workspace(
        cls,
        workspace_path: Path,
        settings_file: Optional[Path] = None,
    ) -> bool:
        """Register workspace path and its worktree parent in agy-cli trustedWorkspaces.

        Args:
            workspace_path: Path to workspace or worktree directory.
            settings_file: Optional custom path to settings.json (for testing or overrides).

        Returns:
            bool: True if settings were successfully checked or updated, False otherwise.
        """
        try:
            target_settings = (
                settings_file
                if settings_file is not None
                else Path.home() / ".gemini" / "antigravity-cli" / "settings.json"
            )
            target_settings.parent.mkdir(parents=True, exist_ok=True)

            data = {}
            if target_settings.is_file():
                try:
                    with open(target_settings, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}

            if not isinstance(data, dict):
                data = {}

            trusted = data.get("trustedWorkspaces")
            if not isinstance(trusted, list):
                trusted = []

            resolved_ws = Path(workspace_path).resolve()
            paths_to_add = [str(resolved_ws)]

            # Check if this path is inside a .worktrees directory
            for parent in resolved_ws.parents:
                if parent.name == ".worktrees":
                    paths_to_add.append(str(parent))
                    break

            modified = False
            for p in paths_to_add:
                # Normalize comparison
                norm_p = str(Path(p).resolve())
                already_present = any(
                    str(Path(existing).resolve()) == norm_p
                    for existing in trusted
                    if isinstance(existing, str)
                )
                if not already_present:
                    trusted.append(str(p))
                    modified = True

            if modified or "trustedWorkspaces" not in data:
                data["trustedWorkspaces"] = trusted
                with open(target_settings, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)

            return True
        except Exception:
            return False

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
                    cls.trust_workspace(cp)
                    cls.setup_worktree_env(cp, repo_root=repo_root)
                    break
            else:
                cls.trust_workspace(Path(path))

        return True, path, pane_id

    @classmethod
    def start_agent(
        cls,
        task_id: str,
        pane_id: str,
        kind: str = "agy",
        dangerously_skip_permissions: bool = True,
        effort: str = "low",
        system_prompt_file: Optional[str] = None,
        thinking_level: Optional[str] = None,
        skill_files: Optional[List[str]] = None,
        model: Optional[str] = None,
        executable: str = "herdr",
        inject_agents_rule: bool = False,
        repo_root: Optional[Path] = None,
    ) -> Tuple[bool, str]:
        """Run 'herdr agent start worker_<task_id> --kind <kind> --pane <pane_id>'.

        Args:
            task_id: Task identifier.
            pane_id: Pane ID where the interactive agent will run.
            kind: Agent kind (default: 'agy').
            dangerously_skip_permissions: Auto-approve permissions if True.
            effort: Model reasoning effort (default: 'low').
            system_prompt_file: Optional path to system prompt / skill file.
            thinking_level: Optional model thinking level (e.g. 'low', 'medium', 'high').
            skill_files: Optional list of skill file paths to inject.
            model: Optional model identifier (defaults to active user model).
            executable: Herdr executable binary name or path.
            inject_agents_rule: If True, pre-flight verify AGENTS.md and prepend into system prompt.
            repo_root: Optional repository root path for AGENTS.md preflight verification.

        Returns:
            Tuple[bool, str]: (success, output_or_error_message)
        """
        effective_spf = system_prompt_file
        if inject_agents_rule:
            root = repo_root or Path.cwd()
            try:
                agents_rule = verify_and_load_agents_rule(root)
            except Exception as exc:
                return False, f"Pre-flight AGENTS.md verification failed: {exc}"

            # If system_prompt_file provided, inject at top of system prompt
            if system_prompt_file:
                spf = Path(system_prompt_file)
                if not spf.exists():
                    return False, f"System prompt file not found: {system_prompt_file}"
                try:
                    orig_content = spf.read_text(encoding="utf-8")
                    if agents_rule.strip() not in orig_content:
                        injected_content = f"{agents_rule.strip()}\n\n{orig_content}"
                        spf.write_text(injected_content, encoding="utf-8")
                except Exception as exc:
                    return False, f"Failed injecting AGENTS.md into system prompt file: {exc}"
            else:
                # Create a temporary or dedicated system prompt file with AGENTS.md
                injected_spf = root / ".ai" / f".injected_system_prompt_{task_id}.md"
                injected_spf.parent.mkdir(parents=True, exist_ok=True)
                try:
                    injected_spf.write_text(agents_rule, encoding="utf-8")
                    effective_spf = str(injected_spf)
                except Exception as exc:
                    return False, f"Failed creating injected system prompt file: {exc}"
        elif system_prompt_file:
            spf = Path(system_prompt_file)
            if not spf.exists():
                return False, f"System prompt file not found: {system_prompt_file}"

        if skill_files:
            for sf in skill_files:
                if not Path(sf).exists():
                    return False, f"Skill file not found: {sf}"

        worker_name = cls.get_worker_name(task_id)
        cmd = [executable, "agent", "start", worker_name, "--kind", kind, "--pane", pane_id]
        if effective_spf:
            cmd.extend(["--system-prompt-file", Path(effective_spf).as_posix()])
        if thinking_level:
            cmd.extend(["--thinking-level", str(thinking_level)])

        agy_flags: List[str] = []
        if dangerously_skip_permissions:
            agy_flags.append("--dangerously-skip-permissions")
        if effort:
            agy_flags.extend(["--effort", effort])
        if model and model.strip():
            agy_flags.extend(["--model", model.strip()])
        if skill_files:
            for sf in skill_files:
                agy_flags.extend(["--skill-file", Path(sf).as_posix()])
        if agy_flags:
            cmd.append("--")
            cmd.extend(agy_flags)

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
    def resolve_domain_skills(
        cls,
        intent_or_task: str,
        target_paths: Optional[List[str]] = None,
        repo_root: Optional[Path] = None,
    ) -> List[str]:
        """Resolve relevant domain skill files based on intent and target file paths.

        Tier 1 (Intent & Ceremony Matching):
          - scrum, sprint, backlog -> sdlc-scrum-master, sdlc-planning-task-breakdown
          - standup, daily -> sdlc-daily-standup-planner
          - paper, research -> sdlc-ai-paper-researcher, sdlc-research-to-subagent-plan
          - poc, spike -> sdlc-proof-of-concept-criteria
          - architecture, system design -> sdlc-architecture-planner, sdlc-planning-task-breakdown
          - spec, contract -> sdlc-subtask-specifier, sdlc-api-interface-design

        Tier 2 (Target Path Matching):
          - src/api, src/services, src/models ->
            sdlc-api-interface-design, sdlc-clean-code-standards
          - src/ui, components, static -> sdlc-frontend-ui-engineering, sdlc-clean-code-standards
          - tests/ -> sdlc-test-driven-development, sdlc-clean-code-standards

        Args:
            intent_or_task: Natural language intent or task description.
            target_paths: Optional list of affected or target paths.
            repo_root: Optional repository root path.

        Returns:
            List[str]: Deduplicated list of relative paths under .agents/skills/ in priority order.
        """
        skills_prefix = Path(".agents") / "skills"
        resolved: List[str] = []

        intent_lower = (intent_or_task or "").lower()

        # Tier 0: Role Default Skills Matching
        matched_role: Optional[AgentRole] = None
        try:
            matched_role = AgentRole(intent_or_task)
        except Exception:
            clean_role_candidate = (
                (intent_or_task or "").replace("-", "_").replace(" ", "_").lower()
            )
            for r in AgentRole:
                if r.value == clean_role_candidate or r.value in clean_role_candidate:
                    matched_role = r
                    break

        if matched_role and matched_role in ROLE_DEFAULT_SKILLS:
            for skill_name in ROLE_DEFAULT_SKILLS[matched_role]:
                resolved.append((skills_prefix / skill_name / "SKILL.md").as_posix())

        # Tier 1: Intent & Ceremony Matching
        if any(kw in intent_lower for kw in ["scrum", "sprint", "backlog"]):
            resolved.append((skills_prefix / "sdlc-scrum-master" / "SKILL.md").as_posix())
            resolved.append(
                (skills_prefix / "sdlc-planning-task-breakdown" / "SKILL.md").as_posix()
            )

        if any(kw in intent_lower for kw in ["standup", "daily"]):
            resolved.append((skills_prefix / "sdlc-daily-standup-planner" / "SKILL.md").as_posix())

        if any(kw in intent_lower for kw in ["paper", "research"]):
            resolved.append((skills_prefix / "sdlc-ai-paper-researcher" / "SKILL.md").as_posix())
            resolved.append(
                (skills_prefix / "sdlc-research-to-subagent-plan" / "SKILL.md").as_posix()
            )

        if any(kw in intent_lower for kw in ["poc", "spike"]):
            resolved.append(
                (skills_prefix / "sdlc-proof-of-concept-criteria" / "SKILL.md").as_posix()
            )

        if any(kw in intent_lower for kw in ["architecture", "system design"]):
            resolved.append((skills_prefix / "sdlc-architecture-planner" / "SKILL.md").as_posix())
            resolved.append(
                (skills_prefix / "sdlc-planning-task-breakdown" / "SKILL.md").as_posix()
            )

        if any(kw in intent_lower for kw in ["spec", "contract"]):
            resolved.append((skills_prefix / "sdlc-subtask-specifier" / "SKILL.md").as_posix())
            resolved.append((skills_prefix / "sdlc-api-interface-design" / "SKILL.md").as_posix())

        # Tier 2: Target Path Matching
        if target_paths:
            for p in target_paths:
                p_norm = Path(p).as_posix().lower()
                if any(api_kw in p_norm for api_kw in ["src/api", "src/services", "src/models"]):
                    resolved.append(
                        (skills_prefix / "sdlc-api-interface-design" / "SKILL.md").as_posix()
                    )
                    resolved.append(
                        (skills_prefix / "sdlc-clean-code-standards" / "SKILL.md").as_posix()
                    )
                if any(ui_kw in p_norm for ui_kw in ["src/ui", "components", "static"]):
                    resolved.append(
                        (skills_prefix / "sdlc-frontend-ui-engineering" / "SKILL.md").as_posix()
                    )
                    resolved.append(
                        (skills_prefix / "sdlc-clean-code-standards" / "SKILL.md").as_posix()
                    )
                if "tests/" in p_norm or p_norm.startswith("tests") or "/tests" in p_norm:
                    resolved.append(
                        (skills_prefix / "sdlc-test-driven-development" / "SKILL.md").as_posix()
                    )
                    resolved.append(
                        (skills_prefix / "sdlc-clean-code-standards" / "SKILL.md").as_posix()
                    )

        # Deduplicate while preserving order
        return list(dict.fromkeys(resolved))

    @classmethod
    def format_dispatch_payload(
        cls,
        role: str,
        spec_path: str,
        prohibitions: Optional[List[str]] = None,
        target: Optional[str] = None,
        model: Optional[str] = None,
        target_paths: Optional[List[str]] = None,
        required_skills: Optional[List[str]] = None,
        injected_context: Optional[List[str]] = None,
        output_artifacts: Optional[List[str]] = None,
    ) -> str:
        """Construct strict multi-line payload template for worker dispatch.

        Args:
            role: Worker role identifier (e.g. 'Leaf Coder Worker').
            spec_path: Path to the subtask spec markdown file.
            prohibitions: Optional list of prohibited actions/tools.
            target: Optional target description / deliverables.
            model: Optional model identifier.
            target_paths: Optional list of authorized target file/directory paths.
            required_skills: Optional list of required domain skill identifiers or paths.
            injected_context: Optional list of input artifacts from upstream tasks.
            output_artifacts: Optional list of produced artifacts to validate.

        Returns:
            str: Multi-line formatted dispatch payload string.
        """
        clean_role = role.strip()
        clean_spec = Path(spec_path.strip()).as_posix() if spec_path else ""

        if prohibitions is not None:
            prohibitions_str = ", ".join(p.strip() for p in prohibitions if p.strip())
        else:
            prohibitions_str = "No ManageTask, no background loops, no full-file overwrite."

        if target is not None:
            target_str = target.strip()
        else:
            target_str = "100% pytest pass -> write status .complete -> output [WORKER_COMPLETED]."

        lines = [
            f"[ROLE: {clean_role}]",
            f"Spec: {clean_spec}",
        ]
        if required_skills:
            clean_skills = ", ".join(s.strip() for s in required_skills if s.strip())
            if clean_skills:
                lines.append(f"Required Skills: {clean_skills}")
        if target_paths:
            clean_targets = ", ".join(t.strip() for t in target_paths if t.strip())
            if clean_targets:
                lines.append(f"Target Paths: {clean_targets}")
        if injected_context:
            clean_inputs = ", ".join(c.strip() for c in injected_context if c.strip())
            if clean_inputs:
                lines.append(f"Injected Context: {clean_inputs}")
        if output_artifacts:
            clean_outputs = ", ".join(a.strip() for a in output_artifacts if a.strip())
            if clean_outputs:
                lines.append(f"Output Artifacts: {clean_outputs}")
        if model and model.strip():
            lines.append(f"Model: {model.strip()}")
        lines.extend(
            [
                f"Prohibitions: {prohibitions_str}",
                f"Target: {target_str}",
            ]
        )
        return "\n".join(lines)

    @classmethod
    def prompt_agent(
        cls,
        task_id: str,
        prompt: str,
        wait: bool = False,
        executable: str = "herdr",
        inject_agents_rule: bool = False,
        repo_root: Optional[Union[str, Path]] = None,
    ) -> Tuple[bool, str]:
        """Run 'herdr agent prompt worker_<task_id> "<prompt>"'.

        Args:
            task_id: Task identifier.
            prompt: Prompt instruction text to send to the worker agent.
            wait: Wait for first matching settled state if True.
            executable: Herdr executable binary name or path.
            inject_agents_rule: Whether to preflight-verify and inject AGENTS.md.
            repo_root: Optional repository root path for AGENTS.md verification.

        Returns:
            Tuple[bool, str]: (success, output_or_error_message)
        """
        effective_prompt = prompt
        if inject_agents_rule:
            root = repo_root or Path.cwd()
            try:
                agents_rule = verify_and_load_agents_rule(root)
                if agents_rule.strip() not in effective_prompt:
                    effective_prompt = f"{agents_rule.strip()}\n\n{effective_prompt}"
            except Exception as exc:
                return False, f"Pre-flight AGENTS.md verification failed: {exc}"

        worker_name = cls.get_worker_name(task_id)
        cmd = [executable, "agent", "prompt", worker_name, effective_prompt]
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
        repo_root: Optional[Path] = None,
        executable: str = "herdr",
    ) -> Tuple[bool, str]:
        """Block locally in Python until completion flag file appears or timeout expires.

        Checks status directory, worktree status directory (.worktrees/agent/<task_id>/.ai/status),
        and root status directory (.ai/status).

        Args:
            task_id: Task identifier.
            timeout_seconds: Maximum seconds to wait.
            poll_interval: Seconds between poll checks.
            status_dir: Optional path to status directory. Defaults to .ai/status.
            repo_root: Optional repository root path. Defaults to cwd.
            executable: Herdr executable binary name or path.

        Returns:
            Tuple[bool, str]: (success, message_or_content)
        """
        root = repo_root or Path.cwd()
        sdir = status_dir or (root / ".ai" / "status")
        clean_task_id = task_id.replace("agent/", "").replace("worker_", "")

        # Candidate status directories: explicit/root sdir, and worktree .ai/status
        status_dirs: List[Path] = [Path(sdir)]
        wt_dir = root / ".worktrees" / "agent" / clean_task_id / ".ai" / "status"
        if wt_dir not in status_dirs:
            status_dirs.append(wt_dir)

        start_time = time.time()
        while True:
            for d in status_dirs:
                flag_candidates = [
                    d / f"{task_id}.complete",
                    d / f"{clean_task_id}.complete",
                ]
                for flag in flag_candidates:
                    if flag.is_file():
                        try:
                            content = flag.read_text(encoding="utf-8").strip()
                        except Exception:
                            content = ""

                        # Parse YAML telemetry if present
                        telemetry: Dict[str, Any] = {}
                        if content:
                            try:
                                parsed = yaml.safe_load(content)
                                if isinstance(parsed, dict):
                                    telemetry = parsed
                            except Exception:
                                telemetry = {}

                        elapsed = time.time() - start_time
                        try:
                            prompt_tokens = int(telemetry.get("prompt_tokens") or 0)
                            completion_tokens = int(telemetry.get("completion_tokens") or 0)
                            cached_tokens = int(telemetry.get("cached_tokens") or 0)
                            truncated_tokens = int(
                                telemetry.get("truncated_tokens")
                                or telemetry.get("truncated_output_tokens")
                                or 0
                            )
                            plan_id = str(telemetry.get("plan_id") or "default_plan")
                            raw_model = telemetry.get("model")
                            if isinstance(raw_model, str) and raw_model.strip():
                                model_str = raw_model.strip()
                            else:
                                model_str = get_active_model()
                            role_str = str(telemetry.get("role") or "coder")
                            status_str = str(telemetry.get("status") or "COMPLETED")

                            csv_target = root / ".runs" / "log.csv"
                            TokenLogger.log_task_summary(
                                task_id=clean_task_id,
                                plan_id=plan_id,
                                role=role_str,
                                model=model_str,
                                prompt_tokens=prompt_tokens,
                                completion_tokens=completion_tokens,
                                cached_tokens=cached_tokens,
                                truncated_output_tokens=truncated_tokens,
                                duration_seconds=elapsed,
                                status=status_str,
                                csv_path=csv_target,
                            )
                        except Exception as log_exc:
                            logger.warning(
                                f"Failed to log task summary telemetry for {task_id}: {log_exc}"
                            )

                        return True, content or "[WORKER_COMPLETED]"

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
        cls.trust_workspace(worktree_path)
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


def filter_tools_for_role(
    all_tools: List[Dict[str, Any]],
    role: AgentRole,
) -> List[Dict[str, Any]]:
    """Filters tool declarations based on assigned agent role.

    Args:
        all_tools: Complete list of tool schemas.
        role: The target agent role.

    Returns:
        Pruned list of tools relevant exclusively to the role.
    """
    if not all_tools:
        return []

    # Safe fallback if unknown role or not in allowlist
    allowlist = ROLE_TOOL_ALLOWLIST.get(role)
    if allowlist is None:
        try:
            matched_role = AgentRole(role)
            allowlist = ROLE_TOOL_ALLOWLIST.get(matched_role)
        except Exception:
            allowlist = None

    if allowlist is None:
        # Fallback to safe default toolset (read-only tools)
        logger.warning(
            "Unknown role '%s' encountered during tool filtering. Using safe default.", role
        )
        allowlist = ROLE_TOOL_ALLOWLIST[AgentRole.REVIEWER]

    filtered_tools: List[Dict[str, Any]] = []
    for tool_schema in all_tools:
        if not isinstance(tool_schema, dict):
            logger.warning("Skipping non-dict tool schema: %s", type(tool_schema))
            continue

        tool_name = (
            tool_schema.get("name")
            or tool_schema.get("tool_name")
            or tool_schema.get("function", {}).get("name")
        )
        if not tool_name or not isinstance(tool_name, str):
            logger.warning("Missing or invalid tool name in schema: %s", tool_schema)
            continue

        if tool_name in allowlist:
            filtered_tools.append(tool_schema)

    return filtered_tools


# Module-level aliases
wait_for_task = HerdrDispatcher.wait_for_task
create_feature_branch = HerdrDispatcher.create_feature_branch
merge_worktree_to_feature = HerdrDispatcher.merge_worktree_to_feature
stop_agent = HerdrDispatcher.stop_agent
cleanup_worktree = HerdrDispatcher.cleanup_worktree
setup_worktree_env = HerdrDispatcher.setup_worktree_env
abort_task = HerdrDispatcher.abort_task
dispatch_interactive_critics = HerdrDispatcher.dispatch_interactive_critics
format_dispatch_payload = HerdrDispatcher.format_dispatch_payload
resolve_domain_skills = HerdrDispatcher.resolve_domain_skills
start_agent = HerdrDispatcher.start_agent
prompt_agent = HerdrDispatcher.prompt_agent

HerdrDispatcher.verify_and_load_agents_rule = staticmethod(verify_and_load_agents_rule)

__all__ = [
    "HerdrDispatcher",
    "abort_task",
    "cleanup_worktree",
    "create_feature_branch",
    "dispatch_interactive_critics",
    "filter_tools_for_role",
    "format_dispatch_payload",
    "merge_worktree_to_feature",
    "prompt_agent",
    "resolve_domain_skills",
    "setup_worktree_env",
    "start_agent",
    "stop_agent",
    "verify_and_load_agents_rule",
    "wait_for_task",
]
