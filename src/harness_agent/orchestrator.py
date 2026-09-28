"""AgentOrchestrator: Central coordinator managing worker agents and task DAGs."""

from __future__ import annotations

import json
import os
import re
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
from harness_agent.state import DAGStateStore


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
        state_store: Optional[DAGStateStore] = None,
        db_path: Optional[str] = None,
    ) -> None:
        self.base_config = base_config or AgyConfig()
        self.runner = runner or AgyRunner(self.base_config)
        self.state_store = state_store or DAGStateStore(db_path=db_path)

    @classmethod
    def load_plan(cls, file_path: str) -> OrchestrationPlan:
        """Load an orchestration plan from a YAML file or Markdown with YAML frontmatter."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Plan file not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check for YAML frontmatter in Markdown (e.g. .ai/plan/main_[goal].md)
        if file_path.endswith(".md") or content.startswith("---"):
            match = re.search(r"^---\s*\n(.*?)\n---", content, flags=re.DOTALL)
            if match:
                frontmatter_data = yaml.safe_load(match.group(1))
                if isinstance(frontmatter_data, dict) and "plan_id" in frontmatter_data:
                    return OrchestrationPlan(**frontmatter_data)

        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            raise ValueError(f"Invalid plan format in {file_path}")
        return OrchestrationPlan(**data)

    @classmethod
    def load_plan_from_yaml(cls, yaml_path: str) -> OrchestrationPlan:
        """Load an orchestration plan from a YAML file."""
        return cls.load_plan(yaml_path)

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
            "**MANDATORY FIRST STEP:** Read the `AGENTS.md` file in the repository "
            "root to understand architectural rules, environment setup, and Git protocols.",
            f"Instruction:\n{subtask.instruction}",
        ]

        if subtask.description:
            lines.extend(["", f"Context / Details:\n{subtask.description}"])

        # Render formal Sub-Spec if present
        if subtask.spec:
            spec = subtask.spec
            lines.extend(
                [
                    "",
                    "## Technical Sub-Specification (SDLC Contract):",
                    f"- Criticality: {spec.criticality.value.upper()}",
                    f"- Risk Level: {spec.risk_level.value.upper()}",
                    f"- Status: {spec.status.value.upper()}",
                ]
            )
            if spec.blast_radius:
                lines.append(f"- Blast Radius: {spec.blast_radius}")
            if spec.risk_mitigation:
                lines.append(f"- Risk Mitigation: {spec.risk_mitigation}")

            if spec.functions:
                lines.extend(["", "### Required Functions / Interfaces:"])
                for fn in spec.functions:
                    lines.append(f"```python\n{fn.signature}\n```")
                    if fn.description:
                        lines.append(f"  Docstring: {fn.description}")
                    if fn.parameters:
                        lines.append(f"  Parameters: {fn.parameters}")
                    if fn.raises:
                        lines.append(f"  Raises: {fn.raises}")

            if spec.test_cases:
                lines.extend(["", "### Required Test Cases (QA Acceptance):"])
                for tc in spec.test_cases:
                    lines.append(f"- [{tc.id}] {tc.description}")
                    if tc.input_data:
                        lines.append(f"    Inputs: {tc.input_data}")
                    if tc.expected_output is not None:
                        lines.append(f"    Expected Output: {tc.expected_output}")
                    if tc.expected_exception:
                        lines.append(f"    Expected Exception: {tc.expected_exception}")

            if spec.acceptance_criteria:
                lines.extend(["", "### SDLC Quality Acceptance Criteria:"])
                for crit in spec.acceptance_criteria:
                    lines.append(f"- [ ] {crit}")

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

    async def run_plan(
        self,
        plan: OrchestrationPlan,
        resume: bool = False,
        plan_file: Optional[str] = None,
        initial_statuses: Optional[Dict[str, TaskStatus]] = None,
        initial_results: Optional[Dict[str, RunResult]] = None,
    ) -> OrchestrationResult:
        """Execute the orchestration plan with continuous state serialization and resume support."""
        start_time = time.time()
        ordered_tasks = self.resolve_execution_order(plan.tasks)

        task_results: Dict[str, RunResult] = {}
        task_statuses: Dict[str, TaskStatus] = {}

        if resume:
            if initial_statuses is None:
                saved = self.state_store.load_run_state(plan.plan_id)
                if saved:
                    initial_statuses = saved.get("task_statuses")
                    initial_results = saved.get("task_results")

            if initial_statuses:
                task_statuses = dict(initial_statuses)
                task_results = dict(initial_results or {})

                # Ensure any newly declared tasks in plan are tracked as PENDING
                for t in plan.tasks:
                    if t.id not in task_statuses:
                        task_statuses[t.id] = TaskStatus.PENDING

                # Re-dispatch rule: tasks that were RUNNING, VALIDATING, BLOCKED, or SKIPPED
                # when the orchestrator halted/crashed are reset to PENDING for re-dispatch
                for tid, st in list(task_statuses.items()):
                    if st in (
                        TaskStatus.RUNNING,
                        TaskStatus.VALIDATING,
                        TaskStatus.BLOCKED,
                        TaskStatus.SKIPPED,
                    ):
                        task_statuses[tid] = TaskStatus.PENDING
            else:
                task_statuses = {t.id: TaskStatus.PENDING for t in plan.tasks}
        else:
            task_statuses = {t.id: TaskStatus.PENDING for t in plan.tasks}

        # Continuously persist initial state to SQLite and Markdown
        self.state_store.save_run_state(
            plan=plan,
            task_statuses=task_statuses,
            task_results=task_results,
            status="running",
            plan_file=plan_file,
        )

        completed_count = sum(1 for st in task_statuses.values() if st == TaskStatus.COMPLETED)
        failed_count = sum(1 for st in task_statuses.values() if st == TaskStatus.FAILED)
        aborted = False

        for subtask in ordered_tasks:
            # Skip already completed tasks when resuming
            if task_statuses.get(subtask.id) == TaskStatus.COMPLETED:
                continue

            if aborted:
                task_statuses[subtask.id] = TaskStatus.SKIPPED
                self.state_store.update_task_status(
                    plan_id=plan.plan_id,
                    task_id=subtask.id,
                    status=TaskStatus.SKIPPED,
                    plan_file=plan_file,
                )
                continue

            # Verify if any dependencies failed or are not completed
            has_failed_dep = any(
                task_statuses.get(dep_id) != TaskStatus.COMPLETED for dep_id in subtask.depends_on
            )

            if has_failed_dep:
                task_statuses[subtask.id] = TaskStatus.BLOCKED
                blocked_res = RunResult(
                    task_id=subtask.id,
                    success=False,
                    exit_code=-1,
                    duration_seconds=0.0,
                    error_message=f"Blocked by upstream dependency failure in {subtask.depends_on}",
                )
                task_results[subtask.id] = blocked_res
                failed_count += 1
                self.state_store.update_task_status(
                    plan_id=plan.plan_id,
                    task_id=subtask.id,
                    status=TaskStatus.BLOCKED,
                    result=blocked_res,
                    plan_file=plan_file,
                )
                if plan.stop_on_failure:
                    aborted = True
                continue

            # 1. State: RUNNING
            task_statuses[subtask.id] = TaskStatus.RUNNING
            self.state_store.update_task_status(
                plan_id=plan.plan_id,
                task_id=subtask.id,
                status=TaskStatus.RUNNING,
                plan_file=plan_file,
            )

            # 2. Execute subtask
            result = await self.execute_subtask(plan, subtask, task_results)

            # 3. State: VALIDATING
            task_statuses[subtask.id] = TaskStatus.VALIDATING
            self.state_store.update_task_status(
                plan_id=plan.plan_id,
                task_id=subtask.id,
                status=TaskStatus.VALIDATING,
                result=result,
                plan_file=plan_file,
            )

            task_results[subtask.id] = result

            # 4. State: COMPLETED or FAILED
            if result.success:
                task_statuses[subtask.id] = TaskStatus.COMPLETED
                completed_count += 1
                self.state_store.update_task_status(
                    plan_id=plan.plan_id,
                    task_id=subtask.id,
                    status=TaskStatus.COMPLETED,
                    result=result,
                    plan_file=plan_file,
                )
            else:
                task_statuses[subtask.id] = TaskStatus.FAILED
                failed_count += 1
                self.state_store.update_task_status(
                    plan_id=plan.plan_id,
                    task_id=subtask.id,
                    status=TaskStatus.FAILED,
                    result=result,
                    plan_file=plan_file,
                )
                if plan.stop_on_failure:
                    aborted = True

        total_duration = round(time.time() - start_time, 2)
        overall_success = (failed_count == 0) and (completed_count == len(plan.tasks))
        final_status = "completed" if overall_success else "failed"

        # Final persistent update
        self.state_store.save_run_state(
            plan=plan,
            task_statuses=task_statuses,
            task_results=task_results,
            status=final_status,
            plan_file=plan_file,
        )

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

    async def resume_plan(
        self,
        plan_or_id: Optional[str] = None,
        plan_file: Optional[str] = None,
    ) -> OrchestrationResult:
        """Resume an interrupted or pending orchestration run from disk state."""
        state_data = None
        resolved_plan_file = plan_file

        if plan_or_id and (
            plan_or_id.endswith(".yaml")
            or plan_or_id.endswith(".yml")
            or plan_or_id.endswith(".md")
            or os.path.exists(plan_or_id)
        ):
            resolved_plan_file = plan_or_id
            loaded_plan = self.load_plan(plan_or_id)
            state_data = self.state_store.load_run_state(loaded_plan.plan_id)
            if not state_data:
                # No previous run in SQLite, start fresh
                return await self.run_plan(
                    plan=loaded_plan,
                    resume=False,
                    plan_file=resolved_plan_file,
                )
        elif plan_or_id:
            state_data = self.state_store.load_run_state(plan_or_id)
        else:
            state_data = self.state_store.load_run_state()

        if not state_data:
            target_desc = f" for '{plan_or_id}'" if plan_or_id else ""
            raise ValueError(f"No saved orchestration run found to resume{target_desc}")

        plan = state_data["plan"]
        resolved_plan_file = resolved_plan_file or state_data.get("plan_file")

        return await self.run_plan(
            plan=plan,
            resume=True,
            plan_file=resolved_plan_file,
            initial_statuses=state_data["task_statuses"],
            initial_results=state_data["task_results"],
        )

    def save_result(self, result: OrchestrationResult, output_path: str) -> None:
        """Save orchestration result to disk as formatted JSON."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result.model_dump(), f, indent=2)
