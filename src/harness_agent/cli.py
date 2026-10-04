"""Command line interface for Harness Agent."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path
from typing import List, Optional, Set

import click

from harness_agent.harness import AgentHarness
from harness_agent.models import AgyConfig, OrchestrationResult, Task, TaskStatus
from harness_agent.orchestrator import AgentOrchestrator
from harness_agent.runner import AgyRunner

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
        click.secho(f"✓ agy is ready: {version_info}", fg="green")
    else:
        click.secho(f"✗ agy check failed: {version_info}", fg="red")
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
        click.secho(f"\n✓ Completed in {result.duration_seconds}s", fg="green")
    else:
        click.secho(
            f"\n✗ Failed (exit code {result.exit_code}): {result.error_message or result.stderr}",
            fg="red",
        )
        sys.exit(result.exit_code if result.exit_code != 0 else 1)


@main.command(name="run-suite")
@click.argument("suite_file", type=click.Path(exists=True))
@click.option("--output", "-o", default="runs/eval_report.json", help="Path to save JSON report")
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
    click.echo(f"Overall Success: {'✓ YES' if result.success else '✗ NO'}")
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
    "--output", "-o", default="runs/orchestration_report.json", help="Path to save JSON report"
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
    "--output", "-o", default="runs/orchestration_report.json", help="Path to save JSON report"
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
        click.secho(f"✗ Failed to resume orchestration: {exc}", fg="red")
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
def init_cmd(
    project_name: Optional[str],
    target_dir: Optional[str],
    force: bool,
) -> None:
    """Initialize harness agent rules, Agent.md, and workflow templates in a target directory."""
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
                "Bạn có muốn cập nhật/bổ sung quy chuẩn (Agent.md, skills) vào dự án hiện có?",
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
    repo_root = Path(__file__).resolve().parent.parent.parent
    files_to_copy = ["AGENTS.md", "Agent.md", ".pre-commit-config.yaml"]
    click.echo(f"Đang thiết lập Harness Agent & SDLC rules tại: {target_path}")

    copied = 0
    for filename in files_to_copy:
        src = repo_root / filename
        if not src.exists() and filename == "Agent.md":
            src = repo_root / "AGENTS.md"
        dest = target_path / filename
        if src.exists():
            shutil.copy2(src, dest)
            click.secho(f"  [✓] Created {filename}", fg="green")
            copied += 1

    examples_src = repo_root / "examples" / "orchestrator_plan.yaml"
    if examples_src.exists():
        target_examples = target_path / "examples"
        target_examples.mkdir(parents=True, exist_ok=True)
        shutil.copy2(examples_src, target_examples / "orchestrator_plan.yaml")
        click.secho("  [✓] Created examples/orchestrator_plan.yaml", fg="green")
        copied += 1

    agents_src = repo_root / ".agents"
    if agents_src.exists():
        target_agents = target_path / ".agents"
        shutil.copytree(agents_src, target_agents, dirs_exist_ok=True)
        click.secho("  [✓] Created .agents/skills/ (SDLC Skills)", fg="green")
        copied += 1

    _register_project(repo_root, target_path)
    click.secho(f"\n✓ Successfully initialized {copied} items in {target_path}", fg="cyan")
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


def _ensure_gitignore(target_path: Path) -> None:
    gitignore_path = target_path / ".gitignore"
    entries = [
        "# ========================================\n",
        "# AI Orchestrator & Configs\n",
        "# ========================================\n",
        ".agents/\n",
        ".runs/\n",
        ".ai/\n",
        "AGENTS.md\n",
        "\n# ========================================\n",
        "# OS & IDE\n",
        "# ========================================\n",
        ".DS_Store\n",
        ".vscode/\n",
        ".idea/\n",
        "*.swp\n",
        "*.log\n",
        ".expo/\n",
        ".expo-shared/\n",
        "dist/\n",
        "web-build/\n",
        "node_modules/\n",
        "\n# ========================================\n",
        "# Python / FastAPI Backend\n",
        "# ========================================\n",
        "venv/\n",
        "env/\n",
        ".env\n",
        ".env.*\n",
        "! .env.example\n",
        "__pycache__/\n",
        "*.py[cod]\n",
        "*$py.class\n",
        "*.pyc\n",
        "token.json\n",
        "**/token.json\n",
        "credentials.json\n",
        "**/credentials.json\n",
        "\n# Pytest / Coverage\n",
        ".pytest_cache/\n",
        "htmlcov/\n",
        ".coverage\n",
        ".mypy_cache/\n",
        "\n# ========================================\n",
        "# AI / Data Science / Models\n",
        "# ========================================\n",
        "*.pt\n",
        "*.pth\n",
        "*.onnx\n",
        "*.h5\n",
        "*.pb\n",
        "*.tflite\n",
        "*.safetensors\n",
        "*.ckpt\n",
        "\n*.csv\n",
        "*.tsv\n",
        "*.mp4\n",
        "*.avi\n",
        "*.jpeg\n",
        "*.jpg\n",
        "*.png\n",
        "img/\n",
        "video/\n",
        "\n# Jupyter Notebook temporary data\n",
        ".ipynb_checkpoints/\n",
        "*/.ipynb_checkpoints/*\n",
        "\n# Keystores (DO NOT COMMIT SECRETS)\n",
        "*.jks\n",
        "*.keystore\n",
        "*.p12\n",
        "*.key\n",
        "*.mobileprovision\n",
        "\n#antigravitycli\n",
        ".antigravitycli/\n",
    ]
    if not gitignore_path.exists():
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.writelines(entries)
    else:
        with open(gitignore_path, "r", encoding="utf-8") as f:
            content = f.read()
        if ".agents/" not in content:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                f.writelines(entries)


def _sync_single_project(repo_root: Path, target_path: Path, link: bool = False) -> int:
    target_path.mkdir(parents=True, exist_ok=True)
    _ensure_gitignore(target_path)
    files_to_copy = ["AGENTS.md", "Agent.md", ".pre-commit-config.yaml"]
    copied = 0

    for filename in files_to_copy:
        src = repo_root / filename
        if not src.exists() and filename == "Agent.md":
            src = repo_root / "AGENTS.md"
        dest = target_path / filename
        if src.exists():
            shutil.copy2(src, dest)
            click.secho(f"  [+] Updated {filename}", fg="green")
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

    _register_project(repo_root, target_path)
    return copied


@main.command(name="sync")
@click.argument("target_dir", required=False, default=None)
@click.option("--all", "sync_all", is_flag=True, help="Sync all registered working projects")
@click.option("--link", is_flag=True, help="Create live symlink/junction for SDLC skills")
def sync_cmd(target_dir: Optional[str], sync_all: bool, link: bool) -> None:
    """Synchronize Agent.md, AGENTS.md, and SDLC skills to working projects."""
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
    from harness_agent.scholar import search_ai_papers

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


if __name__ == "__main__":
    main()
