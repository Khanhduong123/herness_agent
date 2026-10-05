"""AgentHarness orchestrator: runs benchmarks and evaluates tasks."""

from __future__ import annotations

import json
import os
import time
from typing import List, Optional

import yaml

from harness_agent.core.models import AgyConfig, EvalReport, RunResult, Task
from harness_agent.core.runner import AgyRunner


class AgentHarness:
    """Benchmark and evaluation harness that executes tasks using agy CLI."""

    def __init__(
        self,
        config: Optional[AgyConfig] = None,
        runner: Optional[AgyRunner] = None,
    ) -> None:
        self.config = config or AgyConfig()
        self.runner = runner or AgyRunner(self.config)

    @classmethod
    def load_suite_from_yaml(cls, yaml_path: str) -> List[Task]:
        """Load a list of tasks from a YAML file."""
        if not os.path.exists(yaml_path):
            raise FileNotFoundError(f"Suite configuration file not found: {yaml_path}")

        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        tasks_data = data.get("tasks", []) if isinstance(data, dict) else data
        return [Task(**t) for t in tasks_data]

    async def run_task(self, task: Task) -> RunResult:
        """Run a single task through the agy runner and evaluate the results."""
        workspace_dir = task.workspace_dir or os.getcwd()
        result = await self.runner.execute_task(task)

        # Run configured evaluators
        if task.checks:
            from harness_agent.evaluation.evaluator import evaluate_task

            evaluate_task(task, result, workspace_dir)

        return result

    async def run_suite(self, suite_name: str, tasks: List[Task]) -> EvalReport:
        """Run a complete suite of tasks sequentially and produce an evaluation report."""
        start_time = time.time()
        results: List[RunResult] = []

        for task in tasks:
            res = await self.run_task(task)
            results.append(res)

        total = len(results)
        passed = sum(1 for r in results if r.success)
        failed = total - passed
        duration = round(time.time() - start_time, 2)
        pass_rate = round((passed / total * 100.0) if total > 0 else 0.0, 2)

        return EvalReport(
            suite_name=suite_name,
            total_tasks=total,
            passed_tasks=passed,
            failed_tasks=failed,
            duration_seconds=duration,
            pass_rate=pass_rate,
            results=results,
        )

    def save_report(self, report: EvalReport, output_path: str) -> None:
        """Save evaluation report to disk as formatted JSON."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report.model_dump(), f, indent=2)
