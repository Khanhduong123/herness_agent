"""Command line interface for Harness Agent."""

from __future__ import annotations

import asyncio
import sys
from typing import Optional

import click

from harness_agent.harness import AgentHarness
from harness_agent.models import AgyConfig, Task
from harness_agent.orchestrator import AgentOrchestrator
from harness_agent.runner import AgyRunner


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


@main.command(name="orchestrate")
@click.argument("plan_file", type=click.Path(exists=True))
@click.option(
    "--output", "-o", default="runs/orchestration_report.json", help="Path to save JSON report"
)
@click.option("--model", default=None, help="Override default model for workers")
@click.option("--effort", default=None, help="Override reasoning effort")
def orchestrate_cmd(
    plan_file: str,
    output: str,
    model: Optional[str],
    effort: Optional[str],
) -> None:
    """Execute an orchestrator plan coordinating multi-agent subtasks."""
    config = AgyConfig(model=model, effort=effort)
    orchestrator = AgentOrchestrator(base_config=config)

    click.echo(f"Loading orchestration plan from {plan_file}...")
    plan = orchestrator.load_plan_from_yaml(plan_file)
    click.echo(f"Goal: {plan.goal}")
    click.echo(f"Total SubTasks: {len(plan.tasks)}")

    result = asyncio.run(orchestrator.run_plan(plan))
    orchestrator.save_result(result, output)

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
        color = "green" if status == "completed" else "red" if status == "failed" else "yellow"
        res = result.task_results.get(task_id)
        dur = f" ({res.duration_seconds}s)" if res else ""
        click.secho(f"[{status.value.upper()}] SubTask '{task_id}'{dur}", fg=color)
        if res and not res.success and res.error_message:
            click.echo(f"       Reason: {res.error_message}")

    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
