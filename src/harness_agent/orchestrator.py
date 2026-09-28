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
        lazy_context: bool = True,
    ) -> None:
        self.base_config = base_config or AgyConfig()
        self.runner = runner or AgyRunner(self.base_config)
        self.lazy_context = lazy_context

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

    def resolve_subtask_plan_file(
        self, subtask: SubTask, workspace_dir: Optional[str] = None
    ) -> Optional[str]:
        """Resolve the path to the subtask plan markdown file (.ai/plan/subtask_[id].md)."""
        if subtask.plan_file:
            candidates = [subtask.plan_file]
            if workspace_dir:
                candidates.append(os.path.join(workspace_dir, subtask.plan_file))
            candidates.append(os.path.abspath(subtask.plan_file))
            for cand in candidates:
                if os.path.isfile(cand):
                    return os.path.abspath(cand)
            return subtask.plan_file

        search_roots = []
        if workspace_dir:
            search_roots.append(os.path.abspath(workspace_dir))
        search_roots.append(os.path.abspath(os.getcwd()))

        expanded_roots: List[str] = []
        for root in search_roots:
            curr = root
            for _ in range(6):
                if curr not in expanded_roots:
                    expanded_roots.append(curr)
                parent = os.path.dirname(curr)
                if parent == curr:
                    break
                curr = parent

        sub_id = str(subtask.id).strip()
        id_num = sub_id[len("subtask_") :] if sub_id.startswith("subtask_") else sub_id

        exact_names = [
            f"subtask_{sub_id}.md",
            f"subtask_{id_num}.md",
            f"{sub_id}.md",
        ]

        for root in expanded_roots:
            plan_dir = os.path.join(root, ".ai", "plan")
            if not os.path.isdir(plan_dir):
                continue

            for name in exact_names:
                candidate = os.path.join(plan_dir, name)
                if os.path.isfile(candidate):
                    return os.path.abspath(candidate)

            try:
                for entry in sorted(os.listdir(plan_dir)):
                    if not entry.endswith(".md"):
                        continue
                    if (
                        entry.startswith(f"subtask_{id_num}_")
                        or entry.startswith(f"subtask_{sub_id}_")
                        or entry.startswith(f"{sub_id}_")
                        or (id_num.isdigit() and entry.startswith(f"subtask_{int(id_num):02d}_"))
                    ):
                        return os.path.abspath(os.path.join(plan_dir, entry))
            except OSError:
                pass

        return None

    def read_subtask_plan(
        self, subtask: SubTask, workspace_dir: Optional[str] = None
    ) -> Optional[str]:
        """Read the specific subtask plan markdown file content if available."""
        if subtask.plan_content:
            return subtask.plan_content

        resolved_path = self.resolve_subtask_plan_file(subtask, workspace_dir=workspace_dir)
        if resolved_path and os.path.isfile(resolved_path):
            with open(resolved_path, "r", encoding="utf-8") as f:
                return f.read()
        return None

    def read_interface_files(
        self, subtask: SubTask, workspace_dir: Optional[str] = None
    ) -> Dict[str, str]:
        """Read the contents of specific interface files relevant to this task."""
        results: Dict[str, str] = {}
        if subtask.interface_contents:
            results.update(subtask.interface_contents)

        if not subtask.interface_files:
            return results

        search_roots = []
        if workspace_dir:
            search_roots.append(os.path.abspath(workspace_dir))
        search_roots.append(os.path.abspath(os.getcwd()))

        expanded_roots: List[str] = []
        for root in search_roots:
            curr = root
            for _ in range(6):
                if curr not in expanded_roots:
                    expanded_roots.append(curr)
                parent = os.path.dirname(curr)
                if parent == curr:
                    break
                curr = parent

        for iface_path in subtask.interface_files:
            if iface_path in results:
                continue

            content = None
            if os.path.isabs(iface_path) and os.path.isfile(iface_path):
                with open(iface_path, "r", encoding="utf-8") as f:
                    content = f.read()
            else:
                for root in expanded_roots:
                    cand = os.path.join(root, iface_path)
                    if os.path.isfile(cand):
                        with open(cand, "r", encoding="utf-8") as f:
                            content = f.read()
                        break

            if content is not None:
                results[iface_path] = content
            else:
                results[iface_path] = f"# Interface file not found on disk: {iface_path}"

        return results

    def _build_worker_prompt(
        self,
        plan: OrchestrationPlan,
        subtask: SubTask,
        worker: WorkerAgentConfig,
        task_results: Optional[Dict[str, RunResult]] = None,
        workspace_dir: Optional[str] = None,
    ) -> str:
        """Construct a contextualized instruction prompt for the worker agent.

        Implements Lazy Context Loading:
        - Ensures worker only receives context for its assigned subtask and no other subtasks.
        - Injects ONLY the specific .ai/plan/subtask_[id].md file.
        - Injects specific interface files (e.g. schema Pydantic files),
          ignoring the rest of the codebase.
        """
        task_results = task_results or {}
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

        # Lazy context: Read and inject specific subtask plan markdown file
        plan_content = self.read_subtask_plan(subtask, workspace_dir=workspace_dir)
        if plan_content:
            lines.extend(
                [
                    "",
                    f"## Subtask Plan Specification ({subtask.id}):",
                    plan_content.strip(),
                ]
            )

        # Lazy context: Read and inject specific interface files relevant to the task
        interfaces = self.read_interface_files(subtask, workspace_dir=workspace_dir)
        if interfaces:
            lines.extend(
                [
                    "",
                    "## Relevant Interface Specifications:",
                    (
                        "The following interface definitions are provided for this task "
                        "(ignoring the rest of the codebase):"
                    ),
                ]
            )
            for path, content in interfaces.items():
                ext = os.path.splitext(path)[1].lstrip(".") or "python"
                lines.extend(
                    [
                        "",
                        f"### Interface File: `{path}`",
                        f"```{ext}",
                        content.strip(),
                        "```",
                    ]
                )

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

        # Upstream task outputs: only included if lazy_context is disabled to prevent context rot
        is_lazy = getattr(plan, "lazy_context", True) and getattr(self, "lazy_context", True)
        if not is_lazy and subtask.depends_on:
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
        task_results: Optional[Dict[str, RunResult]] = None,
        workspace_dir: Optional[str] = None,
    ) -> RunResult:
        """Dispatch a single subtask to its designated worker."""
        task_results = task_results or {}
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

        effective_workspace = subtask.workspace_dir or workspace_dir or os.getcwd()
        prompt = self._build_worker_prompt(
            plan=plan,
            subtask=subtask,
            worker=worker,
            task_results=task_results,
            workspace_dir=effective_workspace,
        )
        runner = AgyRunner(config=worker_config)

        task_def = Task(
            id=subtask.id,
            name=subtask.name,
            prompt=prompt,
            workspace_dir=subtask.workspace_dir,
            checks=subtask.checks,
            timeout_seconds=subtask.timeout_seconds,
        )

        result = await runner.execute_task(task_def)

        # Perform evaluation checks if defined
        if task_def.checks:
            evaluate_task(task_def, result, effective_workspace)

        return result

    # Aliases for dispatch function
    dispatch_subtask = execute_subtask
    dispatch = execute_subtask

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
