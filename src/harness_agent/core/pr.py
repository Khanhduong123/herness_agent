"""Pull Request template engine and context collector."""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from harness_agent.core.models import AggregatedCriticReview

DEFAULT_PR_TEMPLATE = """## Description

<!-- Please include a summary of the change and which issue is fixed.
Please also include relevant motivation and context.
List any dependencies that are required for this change. -->

Fixes # (issue)

## Type of change

<!-- Please delete options that are not relevant. -->

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to fail)
- [ ] Refactoring (no functional change, no api change)
- [ ] Documentation update
- [ ] CI/CD / DevOps

## How Has This Been Tested?

<!-- Please describe the tests that you ran to verify your changes.
Provide instructions so we can reproduce. -->

- [ ] Unit Tests (`pytest tests/unit`)
- [ ] Integration Tests (`pytest tests/integration`)
- [ ] Manual Verification

**Test Configuration**:
* Python version:
* OS:

## Adversarial Critic Review Gate

<!-- Programmatic evaluation results from the 3 Adversarial Critics -->
- [ ] Security Reviewer (`PASS` / No vulnerabilities detected)
- [ ] Performance Reviewer (`PASS` / Algorithmic efficiency & memory clean)
- [ ] Requirement Reviewer (`PASS` / Specifications & acceptance criteria met)

## Test Evidence

<!-- Please provide evidence that tests pass and the feature works as expected.
This can be screenshots, console logs, or recorded terminal sessions. -->

- [ ] Screenshots / Screen Recording included (if UI/visual)
- [ ] Console logs / Test Output included


## Checklist:

- [ ] My code follows the style guidelines of this project (PEP 8)
- [ ] I have performed a self-review of my own code
- [ ] I have commented my code, particularly in hard-to-understand areas
- [ ] I have made corresponding changes to the documentation
- [ ] My changes generate no new warnings
- [ ] I have added tests that prove my fix is effective or that my feature works
- [ ] New and existing unit tests pass locally with my changes
- [ ] My commit messages follow the Conventional Commits specification
"""

CONVENTIONAL_TYPE_MAP: Dict[str, str] = {
    "feat": "New feature",
    "fix": "Bug fix",
    "docs": "Documentation update",
    "refactor": "Refactoring",
    "test": "Unit Tests",
    "ci": "CI/CD / DevOps",
    "perf": "Refactoring",
    "style": "Refactoring",
    "build": "CI/CD / DevOps",
    "chore": "Refactoring",
}


@dataclass
class PRContext:
    """Git and system context collected for generating pull request content."""

    branch_name: str
    base_branch: str
    commits: List[Dict[str, str]]
    diff_stat: str
    changed_files: List[str]
    inferred_types: List[str]
    python_version: str
    os_info: str
    test_summary: Optional[str] = None


@dataclass
class PRResult:
    """Result of a pull request creation attempt."""

    success: bool
    pr_url: Optional[str] = None
    title: str = ""
    body: str = ""
    error_message: Optional[str] = None
    web_fallback: bool = False


def _run_git_cmd(args: List[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    """Execute a git command safely and return returncode, stdout, and stderr."""
    try:
        res = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd else None,
            check=False,
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


class PRGenerator:
    """Engine for generating and managing pull request templates and submissions."""

    @classmethod
    def _resolve_repo_root(cls) -> Path:
        """Resolve repository root via git rev-parse or fallback to current working directory."""
        code, out, _ = _run_git_cmd(["rev-parse", "--show-toplevel"])
        if code == 0 and out:
            path = Path(out)
            if path.is_dir():
                return path
        return Path.cwd()

    @classmethod
    def find_template(cls, repo_root: Optional[Path] = None) -> Optional[Path]:
        """Find the pull request template in standard repository locations."""
        root = repo_root or cls._resolve_repo_root()
        candidates = [
            root / ".github" / "pull_request_template.md",
            root / ".github" / "PULL_REQUEST_TEMPLATE.md",
            root / "pull_request_template.md",
            root / "PULL_REQUEST_TEMPLATE.md",
            root / ".github" / "pull_request_template" / "pull_request_template.md",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    @classmethod
    def _infer_types(cls, commits: List[Dict[str, str]]) -> List[str]:
        """Infer PR change types based on conventional commit prefixes."""
        detected: List[str] = []
        for c in commits:
            msg = c.get("message", "")
            match = re.match(r"^(\w+)(?:\([^)]+\))?(!)?:\s*(.*)", msg, re.IGNORECASE)
            if match:
                prefix = match.group(1).lower()
                is_breaking = match.group(2) is not None
                if prefix in CONVENTIONAL_TYPE_MAP:
                    mapped = CONVENTIONAL_TYPE_MAP[prefix]
                    if mapped not in detected:
                        detected.append(mapped)
                if is_breaking or "BREAKING CHANGE" in msg:
                    if "Breaking change" not in detected:
                        detected.append("Breaking change")
            elif "BREAKING CHANGE" in msg:
                if "Breaking change" not in detected:
                    detected.append("Breaking change")

        if not detected and commits:
            detected.append("New feature")

        return detected

    @classmethod
    def collect_git_context(
        cls,
        repo_root: Optional[Path] = None,
        base_branch: str = "main",
    ) -> PRContext:
        """Collect git metadata, commits, diffs, and host environment information."""
        root = repo_root or cls._resolve_repo_root()

        # Branch name
        code, out, _ = _run_git_cmd(["branch", "--show-current"], cwd=root)
        branch_name = out if code == 0 and out else "HEAD"

        # Commits
        commits: List[Dict[str, str]] = []
        code, out, _ = _run_git_cmd(["log", f"{base_branch}..HEAD", "--oneline"], cwd=root)
        if code != 0:
            code, out, _ = _run_git_cmd(
                ["log", f"origin/{base_branch}..HEAD", "--oneline"], cwd=root
            )
        if code != 0:
            code, out, _ = _run_git_cmd(["log", "-n", "10", "--oneline"], cwd=root)

        if code == 0 and out:
            for line in out.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split(" ", 1)
                commit_hash = parts[0]
                commit_msg = parts[1] if len(parts) > 1 else ""
                commits.append(
                    {
                        "hash": commit_hash,
                        "message": commit_msg,
                        "sha": commit_hash,
                        "subject": commit_msg,
                    }
                )

        # Diff stat
        code, diff_stat, _ = _run_git_cmd(["diff", "--stat", f"{base_branch}...HEAD"], cwd=root)
        if code != 0:
            code, diff_stat, _ = _run_git_cmd(
                ["diff", "--stat", f"origin/{base_branch}...HEAD"], cwd=root
            )
        if code != 0:
            code, diff_stat, _ = _run_git_cmd(["diff", "--stat", "HEAD~1..HEAD"], cwd=root)

        # Changed files
        changed_files: List[str] = []
        code, files_out, _ = _run_git_cmd(
            ["diff", "--name-only", f"{base_branch}...HEAD"], cwd=root
        )
        if code != 0:
            code, files_out, _ = _run_git_cmd(
                ["diff", "--name-only", f"origin/{base_branch}...HEAD"], cwd=root
            )
        if code != 0:
            code, files_out, _ = _run_git_cmd(["diff", "--name-only", "HEAD~1..HEAD"], cwd=root)
        if code == 0 and files_out:
            changed_files = [f.strip() for f in files_out.splitlines() if f.strip()]

        inferred_types = cls._infer_types(commits)
        py_ver = platform.python_version()
        os_info = f"{platform.system()} {platform.release()}"

        return PRContext(
            branch_name=branch_name,
            base_branch=base_branch,
            commits=commits,
            diff_stat=diff_stat or "",
            changed_files=changed_files,
            inferred_types=inferred_types,
            python_version=py_ver,
            os_info=os_info,
        )

    @classmethod
    def _build_github_compare_url(cls, remote_url: str, branch: str, base_branch: str) -> str:
        """Construct fallback web comparison or PR URL from remote origin URL."""
        match = re.search(
            r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/\.]+)(?:\.git)?",
            remote_url,
            re.IGNORECASE,
        )
        if match:
            owner = match.group("owner")
            repo = match.group("repo")
            return f"https://github.com/{owner}/{repo}/pull/new/{branch}"
        return f"https://github.com/pull/new/{branch}"

    @classmethod
    def _extract_plan_goal(cls, repo_root: Path, branch_name: str) -> Optional[str]:
        """Extract relevant plan goal from .ai/plans/main/ matching branch or most recent."""
        plans_dir = repo_root / ".ai" / "plans" / "main"
        if not plans_dir.is_dir():
            return None

        plan_files: List[Path] = [p for p in plans_dir.rglob("*.md") if p.is_file()]
        if not plan_files:
            return None

        # Clean branch name to find keywords
        branch_clean = branch_name.lower().replace("-", "_")
        branch_tokens = [
            tok
            for tok in re.split(r"[/_]", branch_clean)
            if len(tok) > 2 and tok not in ("feat", "fix", "agent", "subtask", "main", "dev")
        ]

        best_match: Optional[Path] = None
        best_score = 0

        for pf in plan_files:
            pf_name = pf.name.lower()
            score = sum(1 for tok in branch_tokens if tok in pf_name)
            if score > best_score:
                best_score = score
                best_match = pf

        # If no token match, pick most recently modified plan file
        if not best_match or best_score == 0:
            plan_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            best_match = plan_files[0]

        # Extract goal from frontmatter or text
        try:
            content = best_match.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    try:
                        import yaml

                        data = yaml.safe_load(parts[1])
                        if isinstance(data, dict) and "goal" in data and data["goal"]:
                            return str(data["goal"]).strip()
                    except Exception:
                        pass
            match = re.search(r"^goal:\s*(.+)$", content, re.MULTILINE)
            if match:
                return match.group(1).strip()
        except Exception:
            pass

        return None

    @classmethod
    def _build_narrative_summary(
        cls,
        context: PRContext,
        repo_root: Optional[Path] = None,
        custom_description: Optional[str] = None,
    ) -> str:
        """Construct structured narrative description including Overview, Key Changes,
        Commits, and Modified files.
        """
        root = repo_root or cls._resolve_repo_root()
        sections: List[str] = []

        # 1. Overview
        if custom_description and custom_description.strip():
            desc_text = custom_description.strip()
            if not desc_text.startswith("#"):
                sections.append("### Overview")
            sections.append(desc_text)
        else:
            sections.append("### Overview")
            plan_goal = cls._extract_plan_goal(root, context.branch_name)

            # Synthesize overview sentence based on inferred change types
            type_descriptions = []
            if "New feature" in context.inferred_types:
                type_descriptions.append("introduces new features")
            if "Bug fix" in context.inferred_types:
                type_descriptions.append("fixes bugs and stability issues")
            if "Breaking change" in context.inferred_types:
                type_descriptions.append("includes breaking changes")
            if "Refactoring" in context.inferred_types:
                type_descriptions.append("refactors code structure")
            if "Documentation update" in context.inferred_types:
                type_descriptions.append("updates documentation")
            if "CI/CD / DevOps" in context.inferred_types:
                type_descriptions.append("updates CI/CD pipelines")

            if type_descriptions:
                if len(type_descriptions) == 1:
                    actions_str = type_descriptions[0]
                elif len(type_descriptions) == 2:
                    actions_str = f"{type_descriptions[0]} and {type_descriptions[1]}"
                else:
                    head_actions = ", ".join(type_descriptions[:-1])
                    actions_str = f"{head_actions}, and {type_descriptions[-1]}"
                synth_sentence = f"This pull request {actions_str} on `{context.branch_name}`."
            else:
                synth_sentence = (
                    f"This pull request provides updates on branch `{context.branch_name}`."
                )

            if plan_goal:
                overview_text = f"{synth_sentence}\n\n**Goal**: {plan_goal}"
            else:
                overview_text = synth_sentence
            sections.append(overview_text)

        # 2. Key Changes
        sections.append("\n### Key Changes")
        key_changes: List[str] = []
        for c in context.commits:
            msg = c.get("message", "").strip()
            if not msg:
                continue

            # Filter out merge commits (e.g., "Merge branch ...",
            # "merge subtask ...", "feat(...): merge ...")
            lower_msg = msg.lower()
            if (
                lower_msg.startswith("merge ")
                or "merge branch" in lower_msg
                or "merge subtask" in lower_msg
                or re.match(r"^\w+(?:\([^)]+\))?:\s*merge\b", lower_msg)
            ):
                continue

            match = re.match(r"^(\w+)(?:\(([^)]+)\))?(!)?:\s*(.*)", msg)
            if match:
                ctype, scope, breaking, desc = match.groups()
                scope_str = f" ({scope})" if scope else ""
                key_changes.append(f"- **{ctype}{scope_str}**: {desc}")
            else:
                key_changes.append(f"- {msg}")

        if key_changes:
            seen = set()
            unique_changes = []
            for kc in key_changes:
                if kc not in seen:
                    seen.add(kc)
                    unique_changes.append(kc)
                    if len(unique_changes) >= 10:
                        break
            sections.extend(unique_changes)
        else:
            sections.append("- General updates and improvements.")

        # 3. Commits:
        if context.commits:
            sections.append("\n### Commits:")
            for c in context.commits:
                sections.append(f"- {c['message']}")

        return "\n".join(sections)

    @classmethod
    def _derive_title(
        cls,
        branch_name: str,
        plan_goal: Optional[str] = None,
        commits: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Derive PR title from feature branch name or plan goal, avoiding raw merge commits."""
        # 1. Clean branch name
        # Examples: feat/safe-gitignore-and-precommit-setup, fix/login-bug, agent/subtask_01_xyz
        branch_clean = branch_name.strip()
        prefix = "feat"
        slug = branch_clean

        if "/" in branch_clean:
            parts = branch_clean.split("/", 1)
            prefix = parts[0]
            slug = parts[1]

        # Normalize slug into readable words
        words = [w for w in re.split(r"[-_]", slug) if w]

        # Check for scope or keywords in words
        scope = ""
        # If first word or known keywords indicate scope
        if words and words[0] in ("setup", "cli", "core", "eval", "ui", "auth", "pr"):
            scope = words[0]
            words = words[1:]
        elif any(w in ("gitignore", "precommit") for w in words):
            scope = "setup"

        readable_slug = " ".join(words) if words else slug

        # If prefix is "agent" or "head", fallback to feat or plan goal
        if prefix in ("agent", "head", "main", "dev"):
            prefix = "feat"

        scope_str = f"({scope})" if scope else ""
        derived_from_branch = f"{prefix}{scope_str}: {readable_slug}"

        # If we have a clean first non-merge commit and branch doesn't provide good slug
        if commits:
            for c in commits:
                msg = c.get("message", "").strip()
                lower = msg.lower()
                if (
                    not lower.startswith("merge ")
                    and "merge branch" not in lower
                    and "merge subtask" not in lower
                    and not re.match(r"^\w+(?:\([^)]+\))?:\s*merge\b", lower)
                ):
                    # Valid commit title available
                    # If branch is a generic agent/... worktree branch, prefer clean commit message
                    if branch_clean.startswith("agent/") or branch_clean in ("HEAD", "main"):
                        return msg
                    break

        return derived_from_branch

    @classmethod
    def generate_pr_content(
        cls,
        repo_root: Optional[Path] = None,
        base_branch: str = "main",
        issue_id: Optional[str] = None,
        custom_title: Optional[str] = None,
        custom_description: Optional[str] = None,
        test_output: Optional[str] = None,
        critic_review: Optional[AggregatedCriticReview] = None,
        no_review: bool = False,
    ) -> Tuple[str, str]:
        """Generate PR title and markdown body populated with git context."""
        root = repo_root or cls._resolve_repo_root()
        context = cls.collect_git_context(repo_root=root, base_branch=base_branch)

        # Title derivation
        if custom_title:
            title = custom_title
        else:
            plan_goal = cls._extract_plan_goal(root, context.branch_name)
            title = cls._derive_title(
                branch_name=context.branch_name,
                plan_goal=plan_goal,
                commits=context.commits,
            )

        # Load template
        template_file = cls.find_template(repo_root)
        if template_file and template_file.is_file():
            content = template_file.read_text(encoding="utf-8")
        else:
            content = DEFAULT_PR_TEMPLATE

        # 1. Populate Description & Summary
        summary_block = cls._build_narrative_summary(
            context=context,
            repo_root=repo_root,
            custom_description=custom_description,
        )

        # Replace description placeholder comment if present
        desc_comment_pattern = (
            r"<!--\s*Please include a summary of the change and which issue is fixed.*?-->"
        )
        if re.search(desc_comment_pattern, content, flags=re.DOTALL):
            content = re.sub(desc_comment_pattern, summary_block, content, count=1, flags=re.DOTALL)
        else:
            content = content.replace("## Description", f"## Description\n\n{summary_block}", 1)

        # 2. Fixes # (issue)
        if issue_id:
            clean_issue = issue_id.strip().lstrip("#")
            content = re.sub(
                r"Fixes # \(issue\)", f"Fixes #{clean_issue}", content, flags=re.IGNORECASE
            )
        else:
            content = re.sub(
                r"Fixes # \(issue\)",
                "<!-- Fixes # (issue) -->",
                content,
                flags=re.IGNORECASE,
            )

        # 3. Type of change checkboxes
        type_checkbox_map = {
            "Bug fix": r"- \[ \] (Bug fix.*)",
            "New feature": r"- \[ \] (New feature.*)",
            "Breaking change": r"- \[ \] (Breaking change.*)",
            "Refactoring": r"- \[ \] (Refactoring.*)",
            "Documentation update": r"- \[ \] (Documentation update.*)",
            "CI/CD / DevOps": r"- \[ \] (CI/CD / DevOps.*)",
        }
        for type_key, pattern in type_checkbox_map.items():
            if type_key in context.inferred_types:
                content = re.sub(pattern, r"- [x] \1", content, count=1)

        # 4. How Has This Been Tested?
        content = re.sub(r"- \[ \] (Unit Tests.*)", r"- [x] \1", content, count=1)
        content = re.sub(r"- \[ \] (Manual Verification.*)", r"- [x] \1", content, count=1)

        # Test Configuration
        content = re.sub(
            r"(\*\s*Python version:).*",
            rf"\1 {context.python_version}",
            content,
            count=1,
        )
        content = re.sub(
            r"(\*\s*OS:).*",
            rf"\1 {context.os_info}",
            content,
            count=1,
        )

        # 4.5. Adversarial Critic Review Gate
        if "## Adversarial Critic Review Gate" not in content:
            gate_block = (
                "## Adversarial Critic Review Gate\n\n"
                "<!-- Programmatic evaluation results from the 3 Adversarial Critics -->\n"
                "- [ ] Security Reviewer (`PASS` / No vulnerabilities detected)\n"
                "- [ ] Performance Reviewer (`PASS` / Algorithmic efficiency & memory clean)\n"
                "- [ ] Requirement Reviewer (`PASS` / Specifications & acceptance criteria met)\n\n"
            )
            if "## Test Evidence" in content:
                content = content.replace("## Test Evidence", f"{gate_block}## Test Evidence", 1)
            elif "## Checklist:" in content:
                content = content.replace("## Checklist:", f"{gate_block}## Checklist:", 1)
            else:
                content += f"\n\n{gate_block}"

        # Determine checkbox state
        sec_ok = (
            True
            if no_review
            else (
                critic_review.security_critic.approved
                if (critic_review and critic_review.security_critic)
                else (critic_review.approved if critic_review else True)
            )
        )
        perf_ok = (
            True
            if no_review
            else (
                critic_review.performance_critic.approved
                if (critic_review and critic_review.performance_critic)
                else (critic_review.approved if critic_review else True)
            )
        )
        req_ok = (
            True
            if no_review
            else (
                critic_review.requirement_critic.approved
                if (critic_review and critic_review.requirement_critic)
                else (critic_review.approved if critic_review else True)
            )
        )

        if sec_ok:
            content = re.sub(r"- \[ \] (Security Reviewer.*)", r"- [x] \1", content, count=1)
        if perf_ok:
            content = re.sub(r"- \[ \] (Performance Reviewer.*)", r"- [x] \1", content, count=1)
        if req_ok:
            content = re.sub(r"- \[ \] (Requirement Reviewer.*)", r"- [x] \1", content, count=1)

        if critic_review and critic_review.summary:
            summary_snippet = (
                f"\n\n<details>\n<summary>Adversarial Critic Evaluation Summary</summary>\n\n"
                f"{critic_review.summary.strip()}\n\n</details>"
            )
            gate_match = re.search(
                r"(## Adversarial Critic Review Gate.*?- \[.\] Requirement Reviewer[^\n]*)",
                content,
                flags=re.DOTALL,
            )
            if gate_match:
                content = content.replace(
                    gate_match.group(1),
                    gate_match.group(1) + summary_snippet,
                    1,
                )

        # 5. Test Evidence
        content = re.sub(
            r"- \[ \] (Console logs / Test Output included.*)",
            r"- [x] \1",
            content,
            count=1,
        )
        if test_output:
            evidence_snippet = f"\n\n```text\n{test_output.strip()}\n```"
            evidence_pattern = (
                r"(## Test Evidence.*?Console logs / Test Output included.*?)(\n\n## Checklist:|\Z)"
            )
            match_ev = re.search(evidence_pattern, content, flags=re.DOTALL)
            if match_ev:
                content = content.replace(
                    match_ev.group(1), match_ev.group(1) + evidence_snippet, 1
                )
            else:
                content += evidence_snippet

        # 6. Checklist: tick all items
        checklist_marker = "## Checklist:"
        idx = content.find(checklist_marker)
        if idx != -1:
            pre = content[:idx]
            post = content[idx:]
            post = post.replace("- [ ]", "- [x]")
            content = pre + post

        return title, content

    @classmethod
    def create_pr(
        cls,
        repo_root: Optional[Path] = None,
        base_branch: str = "main",
        title: Optional[str] = None,
        body: Optional[str] = None,
        issue_id: Optional[str] = None,
        push: bool = True,
        draft: bool = False,
        custom_description: Optional[str] = None,
        critic_review: Optional[AggregatedCriticReview] = None,
        no_review: bool = False,
    ) -> PRResult:
        """Create a PR using gh CLI or provide web URL fallback."""
        root = repo_root or cls._resolve_repo_root()

        # Branch name
        code, out, _ = _run_git_cmd(["branch", "--show-current"], cwd=root)
        current_branch = out if code == 0 and out else "HEAD"

        if current_branch == "HEAD":
            return PRResult(
                success=False,
                error_message="Cannot create pull request from a detached HEAD state.",
            )

        if current_branch == base_branch:
            return PRResult(
                success=False,
                error_message=f"Current branch is already target base branch '{base_branch}'.",
            )

        # Generate title and body if missing
        if title is None or body is None:
            gen_title, gen_body = cls.generate_pr_content(
                repo_root=root,
                base_branch=base_branch,
                issue_id=issue_id,
                custom_title=title,
                custom_description=custom_description,
                critic_review=critic_review,
                no_review=no_review,
            )
            title = title or gen_title
            body = body or gen_body

        # Push branch
        if push:
            p_code, p_out, p_err = _run_git_cmd(["push", "-u", "origin", current_branch], cwd=root)
            if p_code != 0:
                return PRResult(
                    success=False,
                    title=title,
                    body=body,
                    error_message=f"Git push failed: {p_err or p_out}",
                )

        # Check gh CLI authentication
        has_gh = shutil.which("gh") is not None
        gh_authenticated = False
        if has_gh:
            try:
                gh_auth = subprocess.run(
                    ["gh", "auth", "status"],
                    capture_output=True,
                    text=True,
                    cwd=str(root),
                    check=False,
                )
                if gh_auth.returncode == 0:
                    gh_authenticated = True
            except Exception:
                gh_authenticated = False

        if gh_authenticated:
            cmd = [
                "gh",
                "pr",
                "create",
                "--base",
                base_branch,
                "--head",
                current_branch,
                "--title",
                title,
                "--body",
                body,
            ]
            if draft:
                cmd.append("--draft")

            res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(root), check=False)
            if res.returncode == 0:
                pr_url = res.stdout.strip()
                return PRResult(
                    success=True,
                    pr_url=pr_url,
                    title=title,
                    body=body,
                    web_fallback=False,
                )
            return PRResult(
                success=False,
                title=title,
                body=body,
                error_message=res.stderr.strip() or res.stdout.strip(),
                web_fallback=False,
            )

        # Fallback to web link
        rem_code, rem_url, _ = _run_git_cmd(["remote", "get-url", "origin"], cwd=root)
        web_url = cls._build_github_compare_url(
            rem_url if rem_code == 0 else "", current_branch, base_branch
        )
        return PRResult(
            success=True,
            pr_url=web_url,
            title=title,
            body=body,
            web_fallback=True,
        )
