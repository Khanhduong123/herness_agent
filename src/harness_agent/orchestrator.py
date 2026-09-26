"""AgentOrchestrator: Central coordinator managing worker agents and task DAGs."""

from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional, Set

import yaml

from harness_agent.evaluator import evaluate_task
from harness_agent.models import (
    AgentRole,
    AgyConfig,
    OrchestrationPlan,
    OrchestrationResult,
    RunResult,
    SubTask,
    Task,
    TaskStatus,
    WorkerAgentConfig,
)
from harness_agent.runner import AgyRunner


class AgentOrchestrator:
    """Central orchestrator that breaks down goals, coordinates worker agents,

    resolves dependencies, and tracks execution status across multi-agent tasks.
    """

    DEFAULT_WORKERS: Dict[AgentRole, WorkerAgentConfig] = {
        AgentRole.RESEARCHER: WorkerAgentConfig(
            role=AgentRole.RESEARCHER,
            name="researcher-agent",
            effort="high",
            system_prompt=(
                "You are a researcher agent. Analyze requirements, codebase, and documentation."
            ),
        ),
        AgentRole.CODER: WorkerAgentConfig(
            role=AgentRole.CODER,
            name="coder-agent",
            effort="high",
            system_prompt=(
                "You are a senior software engineering agent. "
                "Write clean, modular, and PEP 8 compliant code."
            ),
        ),
        AgentRole.TESTER: WorkerAgentConfig(
            role=AgentRole.TESTER,
            name="tester-agent",
            effort="medium",
            system_prompt=(
                "You are a QA automation agent. Write and execute thorough unit tests with pytest."
            ),
        ),
        AgentRole.REVIEWER: WorkerAgentConfig(
            role=AgentRole.REVIEWER,
            name="reviewer-agent",
            effort="high",
            system_prompt=(
                "You are a senior code reviewer. "
                "Review changes for security, performance, and code standards."
            ),
        ),
    }

    def __init__(
        self,
        base_config: Optional[AgyConfig] = None,
        runner: Optional[AgyRunner] = None,
    ) -> None:
        self.base_config = base_config or AgyConfig()
        self.runner = runner or AgyRunner(self.base_config)

    @classmethod
    def load_plan_from_yaml(cls, yaml_path: str) -> OrchestrationPlan:
        """Load an orchestration plan from a YAML file."""
        if not os.path.exists(yaml_path):
            raise FileNotFoundError(f"Plan file not found: {yaml_path}")

        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return OrchestrationPlan(**data)

    def resolve_execution_order(self, tasks: List[SubTask]) -> List[SubTask]:
        """Order tasks topologically based on their depends_on declarations."""
        task_map = {t.id: t for t in tasks}
        visited: Set[str] = set()
        temp_marked: Set[str] = set()
        ordered: List[SubTask] = []

        def visit(task_id: str) -> None:
            if task_id in temp_marked:
                raise ValueError(f"Cyclic dependency detected involving task '{task_id}'")
            if task_id not in visited:
                temp_marked.add(task_id)
                task = task_map.get(task_id)
                if not task:
                    raise KeyError(f"Task '{task_id}' declared in dependency does not exist")
                for dep_id in task.depends_on:
                    visit(dep_id)
                temp_marked.remove(task_id)
                visited.add(task_id)
                ordered.append(task)

        for task in tasks:
            if task.id not in visited:
                visit(task.id)

        return ordered

    def _build_worker_prompt(
        self,
        plan: OrchestrationPlan,
        subtask: SubTask,
        worker: WorkerAgentConfig,
        task_results: Dict[str, RunResult],
    ) -> str:
        """Construct a contextualized instruction prompt for the worker agent."""
        lines = [
            f"# Role: {worker.name} ({worker.role.value.upper()})",
            f"Overall Objective: {plan.goal}",
            "",
            f"## Assigned SubTask: {subtask.name} (ID: {subtask.id})",
            f"Instruction:\n{subtask.instruction}",
        ]

        if subtask.description:
            lines.extend(["", f"Context / Details:\n{subtask.description}"])

        # Add context from upstream dependencies
        if subtask.depends_on:
            lines.extend(["", "## Upstream Task Outputs:"])
            for dep_id in subtask.depends_on:
                dep_res = task_results.get(dep_id)
                if dep_res:
                    status_str = "SUCCESS" if dep_res.success else "FAILED"
                    lines.append(f"### Output from Task '{dep_id}' [{status_str}]:")
                    preview = (
                        dep_res.output_text[:1000] + "..."
                        if len(dep_res.output_text) > 1000
                        else dep_res.output_text
                    )
                    lines.append(preview or "(no text output)")

        return "\n".join(lines)

    async def execute_subtask(
        self,
        plan: OrchestrationPlan,
        subtask: SubTask,
        task_results: Dict[str, RunResult],
    ) -> RunResult:
        """Dispatch a single subtask to its designated worker."""
        # Find worker configuration
        worker = plan.workers.get(subtask.role.value) or self.DEFAULT_WORKERS.get(
            subtask.role,
            WorkerAgentConfig(role=subtask.role, name=f"{subtask.role.value}-worker"),
        )

        # Merge runner config with worker specifics
        worker_config = self.base_config.model_copy()
        if worker.model:
            worker_config.model = worker.model
        if worker.effort:
            worker_config.effort = worker.effort
        if worker.extra_flags:
            worker_config.extra_flags.extend(worker.extra_flags)

        prompt = self._build_worker_prompt(plan, subtask, worker, task_results)
        runner = AgyRunner(config=worker_config)

        task_def = Task(
            id=subtask.id,
            name=subtask.name,
            prompt=prompt,
            workspace_dir=subtask.workspace_dir,
            checks=subtask.checks,
            timeout_seconds=subtask.timeout_seconds,
        )

        workspace_dir = task_def.workspace_dir or os.getcwd()
        result = await runner.execute_task(task_def)

        # Perform evaluation checks if defined
        if task_def.checks:
            evaluate_task(task_def, result, workspace_dir)

        return result

    async def run_plan(self, plan: OrchestrationPlan) -> OrchestrationResult:
        """Execute the complete orchestration plan according to the dependency DAG."""
        start_time = time.time()
        ordered_tasks = self.resolve_execution_order(plan.tasks)

        task_results: Dict[str, RunResult] = {}
        task_statuses: Dict[str, TaskStatus] = {t.id: TaskStatus.PENDING for t in plan.tasks}

        completed_count = 0
        failed_count = 0
        aborted = False

        for subtask in ordered_tasks:
            if aborted:
                task_statuses[subtask.id] = TaskStatus.SKIPPED
                continue

            # Verify if any dependencies failed
            has_failed_dep = any(
                task_statuses.get(dep_id) != TaskStatus.COMPLETED for dep_id in subtask.depends_on
            )

            if has_failed_dep:
                task_statuses[subtask.id] = TaskStatus.BLOCKED
                task_results[subtask.id] = RunResult(
                    task_id=subtask.id,
                    success=False,
                    exit_code=-1,
                    duration_seconds=0.0,
                    error_message=f"Blocked by upstream dependency failure in {subtask.depends_on}",
                )
                failed_count += 1
                if plan.stop_on_failure:
                    aborted = True
                continue

            # Execute subtask
            task_statuses[subtask.id] = TaskStatus.RUNNING
            result = await self.execute_subtask(plan, subtask, task_results)
            task_results[subtask.id] = result

            if result.success:
                task_statuses[subtask.id] = TaskStatus.COMPLETED
                completed_count += 1
            else:
                task_statuses[subtask.id] = TaskStatus.FAILED
                failed_count += 1
                if plan.stop_on_failure:
                    aborted = True

        total_duration = round(time.time() - start_time, 2)
        overall_success = (failed_count == 0) and (completed_count == len(plan.tasks))

        summary = (
            f"Orchestration completed with {completed_count}/{len(plan.tasks)} tasks successful."
            if overall_success
            else f"Orchestration stopped or encountered errors: {failed_count} task(s) failed."
        )

        return OrchestrationResult(
            plan_id=plan.plan_id,
            goal=plan.goal,
            success=overall_success,
            total_tasks=len(plan.tasks),
            completed_tasks=completed_count,
            failed_tasks=failed_count,
            duration_seconds=total_duration,
            task_results=task_results,
            task_statuses=task_statuses,
            summary=summary,
        )

    def save_result(self, result: OrchestrationResult, output_path: str) -> None:
        """Save orchestration result to disk as formatted JSON."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result.model_dump(), f, indent=2)
