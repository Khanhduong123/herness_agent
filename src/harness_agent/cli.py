"""Command line interface for Harness Agent."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Set

import click

from harness_agent.core.dispatch import HerdrDispatcher
from harness_agent.core.harness import AgentHarness
from harness_agent.core.models import (
    ROLE_REGISTRY,
    AgyConfig,
    ArchitectureSpec,
    DirectoryLayoutSpec,
    OrchestrationResult,
    Task,
    TaskStatus,
    TechStackSpec,
)
from harness_agent.core.orchestrator import AgentOrchestrator, conduct_role_selection
from harness_agent.core.runner import AgyRunner
from harness_agent.core.skills import ProjectSkillAutoScaffolder
from harness_agent.core.smoke import LiveSmokeProbe


def _get_git_diff(
    base: str, target: str = "HEAD", repo_root: Optional[Path] = None
) -> Optional[str]:
    """Safely obtain git diff between base and target refs."""
    try:
        proc = subprocess.run(
            ["git", "diff", f"{base}...{target}"],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(repo_root) if repo_root else None,
        )
        if proc.returncode == 0:
            return proc.stdout
        proc = subprocess.run(
            ["git", "diff", f"origin/{base}...{target}"],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(repo_root) if repo_root else None,
        )
        if proc.returncode == 0:
            return proc.stdout
        return None
    except Exception:
        return None


if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


@click.group()
@click.version_option(version="0.1.0", prog_name="harness-agent")
def main() -> None:
    """Harness Agent: Benchmark and execution harness for agy CLI."""
    pass


@main.command(name="review")
@click.option("--base", default="main", help="Base branch to compare against (default: main)")
@click.option("--target", default="HEAD", help="Target ref or branch (default: HEAD)")
@click.option(
    "--fail-on-reject/--allow-reject",
    default=True,
    help="Fail with exit code 1 if any critic rejects (default: True)",
)
@click.option(
    "--output",
    "-o",
    default=".runs/critics_report.json",
    help="Optional path to save markdown/json report (defaults to .runs/critics_report.json)",
)
@click.option(
    "--diff-file",
    default=None,
    help="Optional pre-generated diff file to inspect",
)
def review_cmd(
    base: str,
    target: str,
    fail_on_reject: bool,
    output: Optional[str],
    diff_file: Optional[str],
) -> None:
    """Run parallel Adversarial Critics (Security, Performance, Requirement) on diff."""
    from harness_agent.evaluation.critics import dispatch_parallel_critics

    if diff_file:
        diff_path = Path(diff_file)
        if not diff_path.is_file():
            click.secho(f"[FAIL] Diff file not found: {diff_file}", fg="red")
            sys.exit(1)
        diff_content = diff_path.read_text(encoding="utf-8", errors="replace")
    else:
        diff_content = _get_git_diff(base, target)
        if diff_content is None:
            click.secho(
                f"[FAIL] Failed to obtain git diff between '{base}' and '{target}'.",
                fg="red",
            )
            sys.exit(1)

    runner = AgyRunner()
    review = asyncio.run(dispatch_parallel_critics(runner=runner, diff_or_content=diff_content))

    click.echo("=" * 60)
    click.echo("             ADVERSARIAL CRITIC REVIEW REPORT")
    click.echo("=" * 60)
    status_label = "[PASSED]" if review.approved else "[FAILED]"
    click.echo(f"Overall Status: {status_label}")
    click.echo(f"Base: {base} ... Target: {target}")
    click.echo("-" * 60)
    click.echo("Critics Feedback:")
    for role_name, cf in review.critics_feedback.items():
        res_label = "[PASSED]" if cf.approved else "[FAILED]"
        click.echo(f"  * {cf.critic_name} ({cf.role.value}): {res_label}")
        if cf.issues:
            for issue in cf.issues:
                click.echo(f"      - {issue}")
    click.echo("=" * 60)

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if str(output).endswith(".json"):
            out_path.write_text(review.model_dump_json(indent=2), encoding="utf-8")
        else:
            out_path.write_text(review.summary, encoding="utf-8")
        click.echo(f"Report saved to: {output}")

    if review.approved:
        click.secho("[OK] Adversarial Critic Review: PASSED", fg="green")
    else:
        click.secho("[FAIL] Adversarial Critic Review: REJECTED", fg="red")
        if fail_on_reject:
            sys.exit(1)


@main.command()
@click.option("--executable", default="agy", help="Path to agy executable or binary name")
def check(executable: str) -> None:
    """Verify that the agy CLI is installed, accessible, and functioning."""
    config = AgyConfig(executable_path=executable)
    runner = AgyRunner(config=config)
    found = runner.find_executable()
    click.echo(f"Searching for agy executable... Found: {found or 'Not Found on PATH'}")

    ok, version_info = runner.check_version()
    if ok:
        click.secho(f"[OK] agy is ready: {version_info}", fg="green")
    else:
        click.secho(f"[FAIL] agy check failed: {version_info}", fg="red")
        sys.exit(1)


@main.command(name="run-prompt")
@click.argument("prompt")
@click.option("--model", default=None, help="Agent model (e.g. gemini-2.5-pro, gemini-2.5-flash)")
@click.option("--effort", default=None, help="Effort level (low, medium, high, max)")
@click.option("--mode", default=None, help="Agent execution mode (plan, accept-edits)")
@click.option("--timeout", default=120, type=int, help="Execution timeout in seconds")
@click.option(
    "--dangerously-skip-permissions/--require-permissions",
    default=True,
    help="Auto-approve tool permissions",
)
def run_prompt_cmd(
    prompt: str,
    model: Optional[str],
    effort: Optional[str],
    mode: Optional[str],
    timeout: int,
    dangerously_skip_permissions: bool,
) -> None:
    """Run a single prompt through agy and print output."""
    config = AgyConfig(
        model=model,
        effort=effort,
        mode=mode,
        timeout_seconds=timeout,
        dangerously_skip_permissions=dangerously_skip_permissions,
    )
    task = Task(id="adhoc", name="Ad-hoc Prompt", prompt=prompt)
    harness = AgentHarness(config=config)

    click.echo(f"Running prompt via agy: '{prompt}'...")
    result = asyncio.run(harness.run_task(task))

    if result.success:
        click.secho("\n--- Output ---", fg="cyan")
        click.echo(result.output_text)
        click.secho(f"\n[OK] Completed in {result.duration_seconds}s", fg="green")
    else:
        err = result.error_message or result.stderr
        click.secho(
            f"\n[FAIL] Failed (exit code {result.exit_code}): {err}",
            fg="red",
        )
        sys.exit(result.exit_code if result.exit_code != 0 else 1)


@main.command(name="run-suite")
@click.argument("suite_file", type=click.Path(exists=True))
@click.option("--output", "-o", default=".runs/eval_report.json", help="Path to save JSON report")
@click.option("--model", default=None, help="Override model for the suite")
@click.option("--effort", default=None, help="Override reasoning effort")
def run_suite_cmd(
    suite_file: str,
    output: str,
    model: Optional[str],
    effort: Optional[str],
) -> None:
    """Execute a YAML benchmark suite with agy and generate a report."""
    config = AgyConfig(model=model, effort=effort)
    harness = AgentHarness(config=config)

    click.echo(f"Loading suite from {suite_file}...")
    tasks = harness.load_suite_from_yaml(suite_file)
    click.echo(f"Loaded {len(tasks)} tasks. Starting execution...")

    report = asyncio.run(harness.run_suite(suite_name=suite_file, tasks=tasks))
    harness.save_report(report, output)

    click.echo("\n================ Evaluation Summary ================")
    click.echo(f"Total Tasks:  {report.total_tasks}")
    click.echo(f"Passed:       {report.passed_tasks}")
    click.echo(f"Failed:       {report.failed_tasks}")
    click.echo(f"Pass Rate:    {report.pass_rate}%")
    click.echo(f"Total Time:   {report.duration_seconds}s")
    click.echo(f"Report saved: {output}")

    for res in report.results:
        status_color = "green" if res.success else "red"
        status_text = "PASS" if res.success else "FAIL"
        click.secho(
            f"[{status_text}] Task {res.task_id} ({res.duration_seconds}s)", fg=status_color
        )
        if not res.success and res.error_message:
            click.echo(f"       Reason: {res.error_message}")


def _print_orchestration_summary(result: OrchestrationResult, output: str) -> None:
    click.echo("\n================ Orchestration Summary ================")
    click.echo(f"Plan ID:         {result.plan_id}")
    click.echo(f"Goal:            {result.goal}")
    click.echo(f"Overall Success: {'[OK] YES' if result.success else '[FAIL] NO'}")
    click.echo(f"Total SubTasks:  {result.total_tasks}")
    click.echo(f"Completed:       {result.completed_tasks}")
    click.echo(f"Failed/Blocked:  {result.failed_tasks}")
    click.echo(f"Duration:        {result.duration_seconds}s")
    click.echo(f"Report saved:    {output}")

    for task_id, status in result.task_statuses.items():
        color = (
            "green"
            if status == TaskStatus.COMPLETED
            else "red" if status == TaskStatus.FAILED else "yellow"
        )
        res = result.task_results.get(task_id)
        dur = f" ({res.duration_seconds}s)" if res else ""
        click.secho(f"[{status.value.upper()}] SubTask '{task_id}'{dur}", fg=color)
        if res and not res.success and res.error_message:
            click.echo(f"       Reason: {res.error_message}")


@main.command(name="orchestrate")
@click.argument("plan_file", type=click.Path(exists=True))
@click.option(
    "--output", "-o", default=".runs/orchestration_report.json", help="Path to save JSON report"
)
@click.option("--model", default=None, help="Override default model for workers")
@click.option("--effort", default=None, help="Override reasoning effort")
@click.option(
    "--resume", is_flag=True, help="Resume execution from existing disk state if available"
)
@click.option("--db", default=None, help="Path to SQLite state database")
def orchestrate_cmd(
    plan_file: str,
    output: str,
    model: Optional[str],
    effort: Optional[str],
    resume: bool,
    db: Optional[str],
) -> None:
    """Execute an orchestrator plan coordinating multi-agent subtasks."""
    config = AgyConfig(model=model, effort=effort)
    orchestrator = AgentOrchestrator(base_config=config, db_path=db)

    click.echo(f"Loading orchestration plan from {plan_file}...")
    plan = orchestrator.load_plan(plan_file)
    click.echo(f"Goal: {plan.goal}")
    click.echo(f"Total SubTasks: {len(plan.tasks)}")

    result = asyncio.run(orchestrator.run_plan(plan, resume=resume, plan_file=plan_file))
    orchestrator.save_result(result, output)
    _print_orchestration_summary(result, output)

    if not result.success:
        sys.exit(1)


@click.command(name="resume")
@click.argument("plan_or_id", required=False, default=None)
@click.option("--db", default=None, help="Path to SQLite state database")
@click.option(
    "--output", "-o", default=".runs/orchestration_report.json", help="Path to save JSON report"
)
@click.option("--model", default=None, help="Override default model for workers")
@click.option("--effort", default=None, help="Override reasoning effort")
def resume_cmd(
    plan_or_id: Optional[str],
    db: Optional[str],
    output: str,
    model: Optional[str],
    effort: Optional[str],
) -> None:
    """Resume an interrupted or pending orchestration run from disk state."""
    config = AgyConfig(model=model, effort=effort)
    orchestrator = AgentOrchestrator(base_config=config, db_path=db)

    target_str = f" for '{plan_or_id}'" if plan_or_id else " (latest active run)"
    click.echo(f"Resuming orchestration run{target_str}...")

    try:
        result = asyncio.run(orchestrator.resume_plan(plan_or_id=plan_or_id))
    except Exception as exc:
        click.secho(f"[FAIL] Failed to resume orchestration: {exc}", fg="red")
        sys.exit(1)

    orchestrator.save_result(result, output)
    _print_orchestration_summary(result, output)

    if not result.success:
        sys.exit(1)


# Register resume command at top level: harness-agent resume
main.add_command(resume_cmd)


# Register run command group: harness-agent run resume
@main.group(name="run")
def run_group() -> None:
    """Execution and run management commands."""
    pass


run_group.add_command(resume_cmd, name="resume")


@main.command(name="init")
@click.argument("project_name", required=False, default=None)
@click.option("--target-dir", "-t", default=None, help="Specific target directory path")
@click.option("--force", "-f", is_flag=True, help="Force update without prompt if directory exists")
@click.option(
    "--interview/--no-interview",
    "--discovery/--no-discovery",
    default=False,
    help="Interactively formulate contract-first ArchitectureSpec into .ai/context/",
)
@click.option(
    "--role-select",
    is_flag=True,
    default=False,
    help="Trigger interactive role and skill selection during setup",
)
def init_cmd(
    project_name: Optional[str],
    target_dir: Optional[str],
    force: bool,
    interview: bool,
    role_select: bool = False,
) -> None:
    """Initialize harness agent rules, AGENTS.md, and workflow templates in a target directory."""
    if not project_name and not target_dir:
        project_name = click.prompt("Nhập tên dự án của bạn", type=str)

    if target_dir:
        target_path = Path(target_dir).resolve()
    else:
        target_path = Path("..").resolve() / (project_name or "new-agent-project")

    if target_path.exists() and any(target_path.iterdir()):
        click.secho(f"\n[CẢNH BÁO] Thư mục '{target_path}' ĐÃ TỒN TẠI trên máy!", fg="yellow")
        if not force:
            confirmed = click.confirm(
                "Bạn có muốn cập nhật/bổ sung quy chuẩn (AGENTS.md, skills) vào dự án hiện có?",
                default=True,
            )
            if not confirmed:
                click.secho("Đã hủy thiết lập.", fg="red")
                return

    target_path.mkdir(parents=True, exist_ok=True)

    # Setup 3-tier architecture directories
    (target_path / ".runs").mkdir(parents=True, exist_ok=True)
    (target_path / ".ai" / "plans" / "main").mkdir(parents=True, exist_ok=True)
    (target_path / ".ai" / "plans" / "subtasks").mkdir(parents=True, exist_ok=True)
    (target_path / ".ai" / "decisions").mkdir(parents=True, exist_ok=True)
    (target_path / ".ai" / "context").mkdir(parents=True, exist_ok=True)

    _ensure_gitignore(target_path)
    _cleanup_legacy_artifacts(target_path)
    repo_root = Path(__file__).resolve().parent.parent.parent
    files_to_copy = ["AGENTS.md"]
    click.echo(f"Đang thiết lập Harness Agent & SDLC rules tại: {target_path}")

    copied = 0
    for filename in files_to_copy:
        src = repo_root / filename
        dest = target_path / filename
        if src.exists():
            shutil.copy2(src, dest)
            click.secho(f"  [+] Created {filename}", fg="green")
            copied += 1

    if _sync_precommit_config(repo_root, target_path):
        copied += 1

    examples_src = repo_root / "examples" / "orchestrator_plan.yaml"
    if examples_src.exists():
        target_examples = target_path / "examples"
        target_examples.mkdir(parents=True, exist_ok=True)
        shutil.copy2(examples_src, target_examples / "orchestrator_plan.yaml")
        click.secho("  [+] Created examples/orchestrator_plan.yaml", fg="green")
        copied += 1

    agents_src = repo_root / ".agents"
    if agents_src.exists():
        target_agents = target_path / ".agents"
        shutil.copytree(agents_src, target_agents, dirs_exist_ok=True)
        click.secho("  [+] Created .agents/skills/ (SDLC Skills)", fg="green")
        if (target_agents / "hooks.json").exists():
            click.secho("  [+] Created .agents/hooks.json (Lifecycle Hooks config)", fg="green")
        copied += 1

    hooks_src = repo_root / ".agents" / "hooks"
    if not hooks_src.exists():
        hooks_src = repo_root / "src" / "harness_agent" / "hooks"
    if hooks_src.exists():
        target_hooks = target_path / ".agents" / "hooks"
        shutil.copytree(hooks_src, target_hooks, dirs_exist_ok=True)
        click.secho("  [+] Created .agents/hooks/ (Lifecycle Hooks)", fg="green")
        copied += 1

    _cleanup_legacy_artifacts(target_path)

    if interview:
        click.secho(
            "\n--- Contract-First Architecture Discovery Interview ---",
            fg="cyan",
            bold=True,
        )
        resolved_proj_name = project_name or target_path.name
        desc = click.prompt(
            "Project architectural overview / description",
            default=f"Architectural specification for {resolved_proj_name}",
        )
        src_dir = click.prompt("Source code directory", default="src")
        tests_unit_dir = click.prompt("Unit test directory", default="tests/unit")
        tests_int_dir = click.prompt("Integration test directory", default="tests/integration")
        primary_lang = click.prompt("Primary programming language", default="python")
        lang_ver = click.prompt("Target language version", default=">=3.10")
        frameworks_input = click.prompt(
            "Target frameworks (comma-separated)", default="", show_default=False
        )
        frameworks = (
            [f.strip() for f in frameworks_input.split(",") if f.strip()]
            if frameworks_input
            else []
        )
        persistence = click.prompt(
            "Database or storage layer (optional, enter to skip)",
            default="",
            show_default=False,
        )
        vector_db = click.prompt(
            "Vector database engine (optional, enter to skip)",
            default="",
            show_default=False,
        )
        protocols_input = click.prompt(
            "API / Communication protocols (comma-separated)", default="CLI"
        )
        api_protocols = (
            [p.strip() for p in protocols_input.split(",") if p.strip()]
            if protocols_input
            else ["CLI"]
        )

        arch_spec = ArchitectureSpec(
            project_name=resolved_proj_name,
            description=desc,
            layout=DirectoryLayoutSpec(
                src_dir=src_dir,
                tests_unit_dir=tests_unit_dir,
                tests_integration_dir=tests_int_dir,
                docs_dir="docs",
            ),
            tech_stack=TechStackSpec(
                primary_language=primary_lang,
                language_version=lang_ver,
                frameworks=frameworks,
                persistence=persistence.strip() or None,
                vector_db=vector_db.strip() or None,
                api_protocols=api_protocols,
            ),
            approved=True,
        )

        AgentOrchestrator.save_architecture_blueprint(spec=arch_spec, repo_root=target_path)
        click.secho(
            "  [+] Created .ai/context/architecture.md & architecture_spec.json",
            fg="green",
        )
        copied += 2

    if role_select:
        click.secho("\n--- Role and Skill Selection ---", fg="cyan", bold=True)
        conduct_role_selection(repo_root=target_path, interactive=True)
        click.secho("  [+] Configured .ai/context/role_selection.json", fg="green")
        copied += 1

    _register_project(repo_root, target_path)
    click.secho(f"\n[OK] Successfully initialized {copied} items in {target_path}", fg="cyan")
    click.echo(
        "agy-cli is now configured to automatically discover rules and context in this repository."
    )


def _get_registry_path(repo_root: Path) -> Path:
    harness_dir = Path.home() / ".harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    return harness_dir / "projects.json"


def _register_project(repo_root: Path, project_path: Path) -> None:
    reg_file = _get_registry_path(repo_root)
    projects: Set[str] = set()
    if reg_file.exists():
        try:
            with open(reg_file, "r", encoding="utf-8") as f:
                projects = set(json.load(f))
        except Exception:
            projects = set()
    projects.add(str(project_path.resolve()))
    with open(reg_file, "w", encoding="utf-8") as f:
        json.dump(sorted(list(projects)), f, indent=2)


def _get_registered_projects(repo_root: Path) -> List[str]:
    reg_file = _get_registry_path(repo_root)
    if reg_file.exists():
        try:
            with open(reg_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _cleanup_legacy_artifacts(target_path: Path) -> None:
    """Clean up legacy duplicate Agent.md and src/harness_agent directories in target."""
    legacy_agent = target_path / "Agent.md"
    if legacy_agent.exists():
        try:
            legacy_agent.unlink()
        except OSError:
            pass

    legacy_pkg = target_path / "src" / "harness_agent"
    if legacy_pkg.exists():
        legacy_hooks = legacy_pkg / "hooks"
        if legacy_hooks.exists():
            shutil.rmtree(legacy_hooks, ignore_errors=True)
        try:
            remaining = [p for p in legacy_pkg.iterdir() if p.name != "__pycache__"]
            if not remaining:
                shutil.rmtree(legacy_pkg, ignore_errors=True)
        except OSError:
            pass

    legacy_src = target_path / "src"
    if legacy_src.exists():
        try:
            src_remaining = [p for p in legacy_src.iterdir() if p.name != "__pycache__"]
            if not src_remaining:
                shutil.rmtree(legacy_src, ignore_errors=True)
        except OSError:
            pass


def _ensure_gitignore(target_path: Path) -> None:
    gitignore_path = target_path / ".gitignore"
    harness_entries = [
        "# Harness Agent & AI Orchestration\n",
        ".agents/\n",
        ".runs/\n",
        ".ai/\n",
        ".worktrees/\n",
        "AGENTS.md\n",
    ]
    if not gitignore_path.exists():
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.writelines(harness_entries)
    else:
        with open(gitignore_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        existing_lines = {line.strip() for line in lines}
        to_append = [entry for entry in harness_entries if entry.strip() not in existing_lines]
        if to_append:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                if lines and not lines[-1].endswith("\n"):
                    f.write("\n")
                f.writelines(to_append)


def _sync_precommit_config(repo_root: Path, target_path: Path) -> bool:
    """Safely setup or update .pre-commit-config.yaml without overwriting existing user hooks."""
    target_precommit = target_path / ".pre-commit-config.yaml"
    src_precommit = repo_root / ".pre-commit-config.yaml"

    if not target_precommit.exists():
        if src_precommit.exists():
            shutil.copy2(src_precommit, target_precommit)
            click.secho(
                "  [+] Created .pre-commit-config.yaml (Branch protection active)", fg="green"
            )
            return True
        return False

    content = target_precommit.read_text(encoding="utf-8")
    if "no-commit-to-branch" not in content:
        hook_snippet = (
            "\n\n  # Harness Agent Branch Protection Hook\n"
            "  - repo: https://github.com/pre-commit/pre-commit-hooks\n"
            "    rev: v4.6.0\n"
            "    hooks:\n"
            "      - id: no-commit-to-branch\n"
            "        args: [--branch, main, --branch, master, --branch, dev, --branch, develop]\n"
        )
        with open(target_precommit, "a", encoding="utf-8") as f:
            f.write(hook_snippet)
        click.secho(
            "  [+] Appended no-commit-to-branch hook to existing .pre-commit-config.yaml",
            fg="green",
        )
        return True
    return False


def _sync_single_project(repo_root: Path, target_path: Path, link: bool = False) -> int:
    target_path.mkdir(parents=True, exist_ok=True)
    _ensure_gitignore(target_path)
    _cleanup_legacy_artifacts(target_path)
    files_to_copy = ["AGENTS.md"]
    copied = 0

    for filename in files_to_copy:
        src = repo_root / filename
        dest = target_path / filename
        if src.exists():
            shutil.copy2(src, dest)
            click.secho(f"  [+] Updated {filename}", fg="green")
            copied += 1

    if _sync_precommit_config(repo_root, target_path):
        copied += 1

    examples_src = repo_root / "examples" / "orchestrator_plan.yaml"
    if examples_src.exists():
        target_examples = target_path / "examples"
        target_examples.mkdir(parents=True, exist_ok=True)
        shutil.copy2(examples_src, target_examples / "orchestrator_plan.yaml")
        click.secho("  [+] Updated examples/orchestrator_plan.yaml", fg="green")
        copied += 1

    agents_src = repo_root / ".agents"
    if agents_src.exists():
        target_agents = target_path / ".agents"
        if link:
            target_skills = target_agents / "skills"
            src_skills = agents_src / "skills"
            target_agents.mkdir(parents=True, exist_ok=True)
            if target_skills.exists() and not target_skills.is_symlink():
                shutil.rmtree(target_skills)
            try:
                target_skills.symlink_to(src_skills, target_is_directory=True)
                click.secho("  [+] Linked .agents/skills/ (Live auto-sync enabled)", fg="green")
                copied += 1
            except (OSError, NotImplementedError):
                shutil.copytree(agents_src, target_agents, dirs_exist_ok=True)
                click.secho("  [+] Synced .agents/skills/ (Copied)", fg="green")
                copied += 1
        else:
            shutil.copytree(agents_src, target_agents, dirs_exist_ok=True)
            click.secho("  [+] Synced .agents/skills/ (SDLC Skills updated)", fg="green")
            copied += 1

        hooks_file = agents_src / "hooks.json"
        if hooks_file.exists():
            target_agents.mkdir(parents=True, exist_ok=True)
            shutil.copy2(hooks_file, target_agents / "hooks.json")
            click.secho("  [+] Synced .agents/hooks.json (Lifecycle Hooks config)", fg="green")
            copied += 1

    hooks_src = repo_root / ".agents" / "hooks"
    if not hooks_src.exists():
        hooks_src = repo_root / "src" / "harness_agent" / "hooks"
    if hooks_src.exists():
        target_hooks = target_path / ".agents" / "hooks"
        shutil.copytree(hooks_src, target_hooks, dirs_exist_ok=True)
        click.secho("  [+] Synced .agents/hooks/ (Lifecycle Hooks)", fg="green")
        copied += 1

    _cleanup_legacy_artifacts(target_path)
    _register_project(repo_root, target_path)
    return copied


@main.command(name="sync")
@click.argument("target_dir", required=False, default=None)
@click.option("--all", "sync_all", is_flag=True, help="Sync all registered working projects")
@click.option("--link", is_flag=True, help="Create live symlink/junction for SDLC skills")
def sync_cmd(target_dir: Optional[str], sync_all: bool, link: bool) -> None:
    """Synchronize AGENTS.md, SDLC skills, and lifecycle hooks to working projects."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    targets: List[Path] = []

    if sync_all:
        registered = _get_registered_projects(repo_root)
        if not registered:
            click.secho("Chua co du an nao duoc dang ky trong danh sach.", fg="yellow")
            return
        targets = [Path(p) for p in registered]
    elif target_dir:
        targets = [Path(target_dir).resolve()]
    else:
        click.secho("Vui long chi dinh thu muc du an can dong bo hoac dung co --all.", fg="yellow")
        return

    total_synced = 0
    for target_path in targets:
        if not target_path.exists():
            click.secho(f"[-] Khong tim thay thu muc: {target_path}", fg="red")
            continue

        click.echo(f"\n--> Dang dong bo quy chuan & skills toi: {target_path}")
        _sync_single_project(repo_root, target_path, link=link)
        total_synced += 1

    click.secho(f"\n[+] Hoan tat dong bo {total_synced} du an!", fg="cyan")


@main.command(name="scholar-search")
@click.argument("query")
@click.option("--limit", default=5, type=int, help="Maximum number of papers to retrieve")
@click.option(
    "--provider",
    default="all",
    type=click.Choice(["all", "arxiv", "openalex"]),
    help="Target scholarly provider",
)
@click.option("--json-output", "--json", "is_json", is_flag=True, help="Output as JSON array")
def scholar_search_cmd(query: str, limit: int, provider: str, is_json: bool) -> None:
    """Search AI & machine learning papers across arXiv and OpenAlex."""
    from harness_agent.research.scholar import search_ai_papers

    providers = None if provider == "all" else [provider]
    result = search_ai_papers(query=query, limit=limit, providers=providers)

    if is_json:
        click.echo(result.model_dump_json(indent=2))
        return

    click.secho(f"\n=== Scholar Search Results for: '{query}' ===", fg="cyan", bold=True)
    click.echo(f"Found {result.total_found} relevant papers (showing top {len(result.papers)}):\n")

    if not result.papers:
        click.secho("[-] No papers found matching query.", fg="yellow")
        return

    for idx, paper in enumerate(result.papers, 1):
        year_str = f" ({paper.year})" if paper.year else ""
        citations_str = (
            f" | Citations: {paper.citation_count}" if paper.citation_count is not None else ""
        )
        click.secho(f"[{idx}] {paper.title}{year_str}", fg="green", bold=True)

        if paper.authors:
            authors_preview = ", ".join(paper.authors[:4])
            if len(paper.authors) > 4:
                authors_preview += " et al."
            click.echo(f"    Authors: {authors_preview}")

        identifiers = []
        if paper.arxiv_id:
            identifiers.append(f"arXiv:{paper.arxiv_id}")
        if paper.doi:
            identifiers.append(f"DOI:{paper.doi}")
        if identifiers:
            click.echo(f"    ID: {' | '.join(identifiers)}{citations_str}")

        if paper.pdf_url:
            click.secho(f"    PDF: {paper.pdf_url}", fg="blue")
        elif paper.landing_url:
            click.secho(f"    URL: {paper.landing_url}", fg="blue")

        if paper.abstract:
            preview = paper.abstract[:220].strip() + ("..." if len(paper.abstract) > 220 else "")
            click.echo(f"    Abstract: {preview}")
        click.echo("")


@main.command(name="web-crawl")
@click.argument("url")
@click.option(
    "--browser/--no-browser",
    default=True,
    help="Use headless browser (crawl4ai) or fast safe_http (builtin)",
)
@click.option("--json-output", "--json", "is_json", is_flag=True, help="Output as JSON")
def web_crawl_cmd(url: str, browser: bool, is_json: bool) -> None:
    """Crawl a web page and extract clean markdown enclosed in untrusted-source tags."""
    from harness_agent.web.builtin import BuiltinProvider
    from harness_agent.web.crawl4ai_provider import Crawl4AIProvider
    from harness_agent.web.safe_http import SafeHTTPError

    try:
        if browser:
            provider = Crawl4AIProvider()
        else:
            provider = BuiltinProvider()
        result = provider.fetch(url)
    except SafeHTTPError as exc:
        click.secho(f"[FAIL] SSRF / Security refusal: {exc}", fg="red")
        sys.exit(1)
    except Exception as exc:
        click.secho(f"[FAIL] Fetch failed: {exc}", fg="red")
        sys.exit(1)

    if is_json:
        click.echo(result.model_dump_json(indent=2))
        return

    click.secho(f"\n=== Web Crawl Result: {result.title or result.url} ===", fg="cyan", bold=True)
    click.echo(f"URL: {result.url}")
    click.echo(f"Fetched at: {result.fetched_at}")
    click.secho("\n--- Content (<untrusted-source>) ---", fg="yellow")
    click.echo(result.wrapped_content or result.content)


@main.command(name="web-search")
@click.argument("query")
@click.option("--limit", default=5, type=int, help="Maximum number of results to retrieve")
@click.option("--json-output", "--json", "is_json", is_flag=True, help="Output as JSON")
def web_search_cmd(query: str, limit: int, is_json: bool) -> None:
    """Execute free web search via DuckDuckGo without API keys."""
    from harness_agent.web.free_search import search_duckduckgo

    try:
        results = search_duckduckgo(query=query, max_results=limit)
    except Exception as exc:
        click.secho(f"[FAIL] Search failed: {exc}", fg="red")
        sys.exit(1)

    if is_json:
        click.echo(json.dumps([r.model_dump() for r in results], indent=2))
        return

    click.secho(f"\n=== Web Search Results for: '{query}' ===", fg="cyan", bold=True)
    if not results:
        click.secho("[-] No results found.", fg="yellow")
        return

    for item in results:
        click.secho(f"[{item.rank}] {item.title}", fg="green", bold=True)
        click.secho(f"    URL: {item.url}", fg="blue")
        if item.snippet:
            click.echo(f"    Snippet: {item.snippet}")
        click.echo("")


@main.command(name="cite-check")
@click.argument("report_file", type=click.Path(exists=True))
@click.option(
    "--sources-dir",
    default=None,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Directory containing source markdown/text files",
)
@click.option("--json-output", "--json", "is_json", is_flag=True, help="Output as JSON")
def cite_check_cmd(report_file: str, sources_dir: Optional[str], is_json: bool) -> None:
    """Audit report citations and verify claims against source documents."""
    from harness_agent.research.citecheck import check_report_file

    try:
        report = check_report_file(report_path=report_file, sources_dir=sources_dir)
    except Exception as exc:
        click.secho(f"[FAIL] Cite check failed: {exc}", fg="red")
        sys.exit(1)

    if is_json:
        click.echo(report.model_dump_json(indent=2))
        return

    click.secho(
        "\n================ Citation Verification Audit ================",
        fg="cyan",
        bold=True,
    )
    click.echo(f"Report File:         {report.report_file}")
    click.echo(f"Total Sentences:     {report.total_sentences}")
    click.echo(f"Total Citations:     {report.total_citations}")
    click.secho(f"Supported Claims:    {report.supported}", fg="green")
    if report.partially_supported:
        click.secho(f"Partially Supported: {report.partially_supported}", fg="yellow")
    if report.wrong_source:
        click.secho(f"Wrong Source:        {report.wrong_source}", fg="magenta")
    if report.unsupported:
        click.secho(f"Unsupported Claims:  {report.unsupported}", fg="red")
    if report.dangling:
        click.secho(f"Dangling Citations:  {report.dangling}", fg="red")
    click.echo(f"Pass Rate:           {report.pass_rate}%")

    if report.pairs:
        click.secho("\n--- Detailed Citation Verdicts ---", fg="cyan")
        for idx, pair in enumerate(report.pairs, 1):
            if pair.verdict == "supported":
                color = "green"
            elif pair.verdict == "partially-supported":
                color = "yellow"
            elif pair.verdict == "wrong-source":
                color = "magenta"
            else:
                color = "red"
            click.secho(
                f"[{idx}] [{pair.verdict.upper()}] (Source: {pair.source_id})",
                fg=color,
                bold=True,
            )
            click.echo(f"    Sentence: {pair.sentence}")
            if pair.details:
                click.echo(f"    Details:  {pair.details}")
            click.echo("")


@main.command(name="dispatch")
@click.option("--task-id", required=True, help="Task ID to branch and name the worker")
@click.option(
    "--spec-file",
    default=None,
    type=click.Path(),
    help="Path to the subtask spec file to instruct the worker with",
)
@click.option("--kind", default="agy", help="Agent kind (default: agy)")
@click.option(
    "--dangerously-skip-permissions/--require-permissions",
    default=True,
    help="Auto-approve tool permissions",
)
@click.option("--prompt", "prompt_override", default=None, help="Custom prompt override")
@click.option("--wait", is_flag=True, default=False, help="Wait for worker agent to finish")
@click.option(
    "--feature",
    "--base",
    "base_ref",
    default=None,
    help="Base branch/reference for the worktree branch",
)
@click.option("--model", default=None, help="Agent model (defaults to active user model)")
def dispatch_cmd(
    task_id: str,
    spec_file: Optional[str],
    kind: str,
    dangerously_skip_permissions: bool,
    prompt_override: Optional[str],
    wait: bool,
    base_ref: Optional[str] = None,
    model: Optional[str] = None,
) -> None:
    """Interactively dispatch a task to a worker agent running in a Herdr workspace."""
    if not spec_file and not prompt_override:
        click.secho("[FAIL] Either --spec-file or --prompt must be provided.", fg="red")
        sys.exit(1)

    prompt_text = prompt_override
    if not prompt_text:
        spec_path = Path(spec_file)  # type: ignore[arg-type]
        if not spec_path.exists():
            click.secho(f"[FAIL] Spec file not found: {spec_file}", fg="red")
            sys.exit(1)
        prompt_text = (
            f"Read {spec_path.resolve()} and implement according to specifications. "
            f"Ensure 100% test pass rate and commit your changes."
        )

    if not HerdrDispatcher.is_herdr_available():
        click.secho("[FAIL] Herdr CLI is not installed or not in PATH.", fg="red")
        sys.exit(1)

    click.echo(f"Creating git worktree for task '{task_id}'...")
    ok, msg_or_path, pane_id = HerdrDispatcher.create_agent_worktree(task_id, base_ref=base_ref)
    if not ok:
        click.secho(f"[FAIL] Failed to create worktree: {msg_or_path}", fg="red")
        sys.exit(1)

    if not pane_id:
        click.secho("[FAIL] Could not extract pane ID from Herdr worktree output.", fg="red")
        sys.exit(1)

    click.secho(f"[OK] Worktree ready: {msg_or_path} (pane: {pane_id})", fg="green")

    start_agent_kwargs = {
        "task_id": task_id,
        "pane_id": pane_id,
        "kind": kind,
        "dangerously_skip_permissions": dangerously_skip_permissions,
    }
    if model is not None:
        start_agent_kwargs["model"] = model
    ok, start_msg = HerdrDispatcher.start_agent(**start_agent_kwargs)
    if not ok:
        click.secho(f"[FAIL] Failed to start agent: {start_msg}", fg="red")
        sys.exit(1)

    worker_name = HerdrDispatcher.get_worker_name(task_id)
    click.secho(f"[OK] Agent started: {worker_name}", fg="green")

    click.echo(f"Submitting prompt to {worker_name}...")
    ok, prompt_msg = HerdrDispatcher.prompt_agent(
        task_id=task_id,
        prompt=prompt_text,
        wait=wait,
    )
    if not ok:
        click.secho(f"[FAIL] Failed to prompt agent: {prompt_msg}", fg="red")
        sys.exit(1)

    click.secho(f"[OK] Dispatched task '{task_id}' to {worker_name} successfully!", fg="green")


@main.group(name="pr")
def pr_group() -> None:
    """Pull request utilities and template automation."""
    pass


@pr_group.command(name="fill")
@click.option("--base", default="main", help="Target base branch (default: main)")
@click.option("--title", default=None, help="Custom PR title")
@click.option("--description", "-d", default=None, help="Custom PR description / overview")
@click.option("--issue", default=None, help="Issue number or identifier to link (Fixes #...)")
@click.option("--output", "-o", default=None, help="Write output to file instead of stdout")
def pr_fill_cmd(
    base: str,
    title: Optional[str],
    description: Optional[str],
    issue: Optional[str],
    output: Optional[str],
) -> None:
    """Generate and preview populated PR template markdown."""
    from harness_agent.core.pr import PRGenerator

    _, generated_body = PRGenerator.generate_pr_content(
        base_branch=base,
        issue_id=issue,
        custom_title=title,
        custom_description=description,
    )
    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(generated_body, encoding="utf-8")
        click.secho(f"[OK] PR template written to {output}", fg="green")
    else:
        click.echo(generated_body)


@pr_group.command(name="create")
@click.option("--base", default="main", help="Target base branch (default: main)")
@click.option("--title", default=None, help="Custom PR title")
@click.option("--description", "-d", default=None, help="Custom PR description / overview")
@click.option("--issue", default=None, help="Issue number or identifier to link")
@click.option(
    "--push/--no-push",
    default=True,
    help="Push current branch to remote before creating PR",
)
@click.option("--draft", is_flag=True, default=False, help="Create PR as draft")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print generated PR without creating or pushing",
)
@click.option(
    "--review/--no-review",
    default=True,
    help="Run adversarial critics review before creating PR",
)
def pr_create_cmd(
    base: str,
    title: Optional[str],
    description: Optional[str],
    issue: Optional[str],
    push: bool,
    draft: bool,
    dry_run: bool,
    review: bool,
) -> None:
    """Automatically populate PR template, push branch, and create PR via gh CLI
    or output web link.
    """
    from harness_agent.core.pr import PRGenerator

    review_res = None
    if review:
        from harness_agent.evaluation.critics import dispatch_parallel_critics

        diff_content = _get_git_diff(base, "HEAD")
        if diff_content is not None:
            runner = AgyRunner()
            review_res = asyncio.run(
                dispatch_parallel_critics(runner=runner, diff_or_content=diff_content)
            )
            if not review_res.approved and not draft:
                click.secho(
                    "[FAIL] Pull request creation aborted: "
                    "Adversarial Critics detected critical issues.",
                    fg="red",
                )
                for cf in review_res.critics_feedback.values():
                    if cf.issues:
                        click.echo(f"  * {cf.critic_name} ({cf.role.value}):")
                        for issue_item in cf.issues:
                            click.echo(f"      - {issue_item}")
                sys.exit(1)
            elif review_res.approved:
                click.secho("[OK] Adversarial Critics approved changes.", fg="green")
            else:
                click.secho(
                    "[WARN] Adversarial Critics detected issues, continuing for draft PR.",
                    fg="yellow",
                )

    if dry_run:
        gen_title, gen_body = PRGenerator.generate_pr_content(
            base_branch=base,
            issue_id=issue,
            custom_title=title,
            custom_description=description,
            critic_review=review_res,
            no_review=(not review),
        )
        click.secho(f"=== PR Title: {gen_title} ===", fg="cyan", bold=True)
        click.echo(gen_body)
        return

    result = PRGenerator.create_pr(
        base_branch=base,
        title=title,
        issue_id=issue,
        push=push,
        draft=draft,
        custom_description=description,
        critic_review=review_res,
        no_review=(not review),
    )

    if not result.success:
        click.secho(f"[FAIL] Failed to create pull request: {result.error_message}", fg="red")
        sys.exit(1)

    if result.web_fallback:
        draft_file = Path(".github") / "PULL_REQUEST_DRAFT.md"
        try:
            draft_file.parent.mkdir(parents=True, exist_ok=True)
            draft_file.write_text(result.body, encoding="utf-8")
            saved_msg = f" (saved description to {draft_file})"
        except Exception:
            saved_msg = ""
        fallback_msg = (
            f"[-] gh CLI unavailable or not authenticated. Direct web PR link:\n"
            f"{result.pr_url}{saved_msg}"
        )
        click.secho(fallback_msg, fg="yellow")
    else:
        click.secho(f"[OK] Pull Request created successfully: {result.pr_url}", fg="green")


@main.group(name="feature")
def feature_group() -> None:
    """Feature branch management commands."""
    pass


@feature_group.command(name="create")
@click.argument("feature_name")
@click.option(
    "--base",
    default="main",
    help="Base branch to create feature branch from (default: main)",
)
def feature_create_cmd(feature_name: str, base: str) -> None:
    """Create and checkout a new feature branch."""
    ok, msg = HerdrDispatcher.create_feature_branch(feature_name=feature_name, base_branch=base)
    if ok:
        click.secho(f"✓ {msg}", fg="green")
    else:
        click.secho(f"✗ Failed to create feature branch: {msg}", fg="red")
        sys.exit(1)


@main.group(name="worktree")
def worktree_group() -> None:
    """Git worktree and worker workspace lifecycle commands."""
    pass


@worktree_group.command(name="merge")
@click.argument("task_id")
@click.option(
    "--into",
    "target_branch",
    required=True,
    help="Target feature branch to merge into",
)
@click.option(
    "--no-ff/--ff",
    default=True,
    help="Use --no-ff merge strategy (default: True)",
)
@click.option(
    "--review/--no-review",
    default=True,
    help="Run adversarial critics review on subtask diff before merging",
)
def worktree_merge_cmd(task_id: str, target_branch: str, no_ff: bool, review: bool) -> None:
    """Merge a completed subtask worktree branch into a feature branch and cleanup."""
    if review:
        from harness_agent.evaluation.critics import dispatch_parallel_critics

        branch_name = HerdrDispatcher.get_branch_name(task_id)
        diff_content = _get_git_diff(target_branch, branch_name)
        if diff_content is not None:
            runner = AgyRunner()
            review_res = asyncio.run(
                dispatch_parallel_critics(runner=runner, diff_or_content=diff_content)
            )
            if not review_res.approved:
                click.secho(
                    f"[FAIL] Worktree merge aborted: Adversarial Critics detected "
                    f"critical issues on '{branch_name}'.",
                    fg="red",
                )
                for cf in review_res.critics_feedback.values():
                    if cf.issues:
                        click.echo(f"  * {cf.critic_name} ({cf.role.value}):")
                        for issue_item in cf.issues:
                            click.echo(f"      - {issue_item}")
                sys.exit(1)
            click.secho("[OK] Adversarial Critics approved changes.", fg="green")

    click.echo(f"Merging worktree branch for task '{task_id}' into '{target_branch}'...")
    ok, msg = HerdrDispatcher.merge_worktree_to_feature(
        task_id=task_id, target_branch=target_branch, no_ff=no_ff
    )
    if ok:
        click.secho(f"✓ {msg}", fg="green")
    else:
        click.secho(f"✗ Failed to merge worktree: {msg}", fg="red")
        sys.exit(1)


@worktree_group.command(name="cleanup")
@click.argument("task_id")
@click.option(
    "--force/--no-force",
    default=True,
    help="Force remove worktree (default: True)",
)
def worktree_cleanup_cmd(task_id: str, force: bool) -> None:
    """Stop worker agent and safely remove its isolated worktree."""
    click.echo(f"Cleaning up worktree for task '{task_id}'...")
    ok, msg = HerdrDispatcher.cleanup_worktree(task_id=task_id, force=force)
    if ok:
        click.secho(f"✓ {msg}", fg="green")
    else:
        click.secho(f"✗ Failed to clean up worktree: {msg}", fg="red")
        sys.exit(1)


@main.command(name="wait")
@click.argument("task_id")
@click.option(
    "--timeout",
    default=600,
    type=int,
    help="Timeout in seconds to wait (default: 600)",
)
@click.option(
    "--poll-interval",
    default=2.0,
    type=float,
    help="Seconds between poll checks (default: 2.0)",
)
def wait_cmd(task_id: str, timeout: int, poll_interval: float) -> None:
    """Wait for a subtask worker agent to complete (blocking, zero tokens)."""
    click.echo(f"Waiting for task '{task_id}' to complete (timeout={timeout}s)...")
    ok, msg = HerdrDispatcher.wait_for_task(
        task_id=task_id, timeout_seconds=timeout, poll_interval=poll_interval
    )
    if ok:
        click.secho(f"✓ Task '{task_id}' completed: {msg}", fg="green")
    else:
        click.secho(f"✗ {msg}", fg="red")
        sys.exit(1)


@main.command(name="abort")
@click.argument("task_id")
@click.option(
    "--reason",
    default="Aborted via CLI",
    help="Reason for aborting task",
)
def abort_cmd(task_id: str, reason: str) -> None:
    """Abort subtask, archive failure diagnostic diff, stop agent, and remove worktree."""
    click.echo(f"Aborting task '{task_id}'...")
    ok, msg = HerdrDispatcher.abort_task(task_id=task_id, reason=reason)
    if ok:
        click.secho(f"✓ {msg}", fg="green")
    else:
        click.secho(f"✗ Failed to abort task: {msg}", fg="red")
        sys.exit(1)


@main.command(name="smoke")
@click.option(
    "--strict/--lenient",
    default=True,
    help="Exit with code 1 if any smoke probe fails (default: strict)",
)
def smoke_cmd(strict: bool) -> None:
    """Execute live out-of-process smoke probes to verify CLI and runtime sanity."""
    click.echo("[SMOKE PROBE] Running live process verification...")
    probe = LiveSmokeProbe()
    results = probe.run_all()

    all_passed = True
    for res in results:
        status_tag = "[OK]" if res.passed else "[FAILED]"
        click.echo(f"{status_tag} {res.name} (exit: {res.exit_code}, {res.duration_seconds:.2f}s)")
        if not res.passed:
            all_passed = False
            if res.error_message:
                click.echo(f"       Reason: {res.error_message}")
            if res.stderr and res.stderr.strip():
                click.echo(f"       Stderr: {res.stderr.strip()[:200]}")

    if all_passed:
        click.echo("[PASSED] All smoke probes succeeded. Live runtime verified.")
    else:
        click.echo("[FAILED] One or more smoke probes failed.")
        if strict:
            sys.exit(1)


@main.group()
def skill() -> None:
    """Inspect, manage, and auto-scaffold project skills."""
    pass


@skill.command(name="scaffold")
@click.option("--force", is_flag=True, default=False, help="Overwrite existing skill files")
def scaffold_skills_cmd(force: bool) -> None:
    """Auto-scaffolds skills based on detected repository frameworks."""
    repo_root = Path.cwd()
    scaffolder = ProjectSkillAutoScaffolder(repo_root=repo_root)
    detected = scaffolder.detect_technologies()
    if not detected:
        click.echo("No detectable frameworks or dependencies found in repository.")
        return

    click.echo(f"Detected {len(detected)} technologies/frameworks:")
    for tech in detected:
        click.echo(f"  - {tech.name} ({tech.category}, from {tech.source_file})")

    created_paths: List[Path] = []
    for tech in detected:
        tech_dir = scaffolder.skills_dir / tech.name
        skill_file = tech_dir / "SKILL.md"
        if skill_file.exists() and force:
            content = scaffolder._generate_skill_content(tech)
            skill_file.write_text(content, encoding="utf-8")
            created_paths.append(skill_file)
            click.echo(f"  [+] Overwrote existing skill: {tech.name} -> {skill_file}")
        elif not skill_file.exists():
            path = scaffolder.scaffold_skill_if_missing(tech)
            if path:
                created_paths.append(path)
                click.echo(f"  [+] Created new skill: {tech.name} -> {path}")
        else:
            click.echo(f"  [SKIP] Skill {tech.name} already exists (use --force to overwrite)")

    click.secho(
        f"\n[OK] Scaffolding complete. {len(created_paths)} skill file(s) generated/updated.",
        fg="green",
    )


@skill.command(name="list")
def list_skills_cmd() -> None:
    """Lists available skills and their binding to roles."""
    skills_dir = Path.cwd() / ".agents" / "skills"
    available_skills: List[str] = []
    if skills_dir.exists():
        for item in sorted(skills_dir.iterdir()):
            if item.is_dir() and (item / "SKILL.md").exists():
                available_skills.append(item.name)

    click.secho("=== Available Skills in Repository ===", fg="cyan", bold=True)
    if available_skills:
        for sk in available_skills:
            click.echo(f"  * {sk}")
    else:
        click.echo("  (No skills found in .agents/skills/)")

    click.echo("")
    click.secho("=== Role-to-Skill Contract Mappings ===", fg="cyan", bold=True)
    for role, contract in sorted(ROLE_REGISTRY.items(), key=lambda x: x[0].value):
        role_label = role.value if hasattr(role, "value") else str(role)
        core_list = ", ".join(contract.core_skills) if contract.core_skills else "(none)"
        opt_list = ", ".join(contract.optional_skills) if contract.optional_skills else "(none)"
        click.echo(f"Role: {role_label}")
        click.echo(f"  Core Skills:     {core_list}")
        click.echo(f"  Optional Skills: {opt_list}")


if __name__ == "__main__":
    main()
