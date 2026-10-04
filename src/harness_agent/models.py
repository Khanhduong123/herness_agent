"""Data models and schemas for Harness Agent."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AgyConfig(BaseModel):
    """Configuration options passed to the agy CLI."""

    executable_path: str = Field(default="agy", description="Path to agy executable or binary name")
    model: Optional[str] = Field(default=None, description="Model to use for the CLI session")
    effort: Optional[str] = Field(
        default=None, description="Reasoning effort: low, medium, high, max"
    )
    mode: Optional[str] = Field(
        default=None, description="Agent execution mode (accept-edits, plan)"
    )
    dangerously_skip_permissions: bool = Field(
        default=True, description="Auto-approve tool permission requests without prompting"
    )
    sandbox: bool = Field(default=False, description="Run in a sandbox with terminal restrictions")
    output_format: str = Field(
        default="stream-json", description="Output format for print mode (text, json, stream-json)"
    )
    timeout_seconds: Optional[int] = Field(
        default=120, description="Command execution timeout in seconds"
    )
    extra_flags: List[str] = Field(
        default_factory=list, description="Additional CLI flags to append to agy invocation"
    )


class TaskCheck(BaseModel):
    """Evaluation check to run after a task finishes."""

    type: str = Field(
        ...,
        description="Type of check: 'file_exists', 'text_match', 'command_exit_zero'",
    )
    target: str = Field(..., description="Target path, regex pattern, or command string")
    expected: Optional[Any] = Field(
        default=None, description="Expected value or outcome (optional)"
    )


class Task(BaseModel):
    """Definition of an evaluation task to run through agy CLI."""

    id: str = Field(..., description="Unique task identifier")
    name: str = Field(..., description="Human-readable task name")
    prompt: str = Field(..., description="Instruction or prompt sent to agy CLI")
    description: Optional[str] = Field(default=None, description="Detailed task description")
    workspace_dir: Optional[str] = Field(
        default=None, description="Working directory for the agent execution"
    )
    checks: List[TaskCheck] = Field(
        default_factory=list, description="Evaluation checks to validate success"
    )
    timeout_seconds: Optional[int] = Field(
        default=None, description="Optional override timeout for this specific task"
    )
    tags: List[str] = Field(default_factory=list, description="Categorization tags")


class ToolCallRecord(BaseModel):
    """Record of a tool call executed during an agy turn."""

    name: str = Field(..., description="Name of the tool executed")
    args: Dict[str, Any] = Field(default_factory=dict, description="Arguments passed to tool")
    output: Optional[str] = Field(default=None, description="Tool execution result")


class AgentRole(str, Enum):
    """Specialized roles for worker agents in the orchestrator architecture."""

    ORCHESTRATOR = "orchestrator"
    CODER = "coder"
    TESTER = "tester"
    REVIEWER = "reviewer"
    RESEARCHER = "researcher"
    SECURITY_REVIEWER = "security_reviewer"
    PERFORMANCE_REVIEWER = "performance_reviewer"
    REQUIREMENT_REVIEWER = "requirement_reviewer"

    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            normalized = value.replace("-", "_").lower()
            for member in cls:
                if member.value == normalized:
                    return member
        return super()._missing_(value)


class CriticFeedback(BaseModel):
    """Feedback and evaluation result from an individual adversarial critic."""

    role: AgentRole = Field(..., description="Critic role that produced this feedback")
    critic_name: str = Field(..., description="Name of the critic agent")
    approved: bool = Field(default=True, description="Whether the critic approves the changes")
    issues: List[str] = Field(
        default_factory=list, description="Specific issues or vulnerabilities caught by this critic"
    )
    feedback: str = Field(default="", description="Detailed commentary and recommendations")
    run_result: Optional[RunResult] = Field(
        default=None, description="Raw execution result from the agent runner if executed"
    )


class AggregatedCriticReview(BaseModel):
    """Aggregated feedback from parallel adversarial critics."""

    approved: bool = Field(default=True, description="True only if all critics approve the changes")
    critics_feedback: Dict[str, CriticFeedback] = Field(
        default_factory=dict, description="Feedback indexed by critic role"
    )
    summary: str = Field(
        default="", description="Combined markdown report summarizing feedback from all critics"
    )

    @property
    def security_critic(self) -> Optional[CriticFeedback]:
        return self.critics_feedback.get(AgentRole.SECURITY_REVIEWER.value)

    @property
    def performance_critic(self) -> Optional[CriticFeedback]:
        return self.critics_feedback.get(AgentRole.PERFORMANCE_REVIEWER.value)

    @property
    def requirement_critic(self) -> Optional[CriticFeedback]:
        return self.critics_feedback.get(AgentRole.REQUIREMENT_REVIEWER.value)


class RunResult(BaseModel):
    """Result of running an agy task."""

    task_id: str
    success: bool
    exit_code: int
    duration_seconds: float
    output_text: str = ""
    stderr: str = ""
    raw_events: List[Dict[str, Any]] = Field(default_factory=list)
    tool_calls: List[ToolCallRecord] = Field(default_factory=list)
    check_results: Dict[str, bool] = Field(default_factory=dict)
    error_message: Optional[str] = None
    critic_review: Optional[AggregatedCriticReview] = None


class EvalReport(BaseModel):
    """Aggregated evaluation report across multiple tasks."""

    suite_name: str
    total_tasks: int
    passed_tasks: int
    failed_tasks: int
    duration_seconds: float
    pass_rate: float
    results: List[RunResult] = Field(default_factory=list)


class TaskStatus(str, Enum):
    """Execution status for subtasks handled by the orchestrator."""

    PENDING = "pending"
    RUNNING = "running"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class WorkerAgentConfig(BaseModel):
    """Configuration for a specialized worker agent."""

    role: AgentRole = Field(..., description="Role assigned to this worker")
    name: str = Field(..., description="Identifier name of the worker agent")
    model: Optional[str] = Field(default=None, description="Model to use (e.g. gemini-2.5-pro)")
    effort: Optional[str] = Field(default=None, description="Reasoning effort level")
    system_prompt: Optional[str] = Field(
        default=None, description="Custom system prompt or role guidance"
    )
    extra_flags: List[str] = Field(default_factory=list, description="Extra agy CLI flags")
    allowed_tools: Optional[List[str]] = Field(
        default=None, description="Permitted tools under tool-locking policy"
    )
    disallowed_tools: List[str] = Field(
        default_factory=list, description="Forbidden tools under tool-locking policy"
    )
    enforce_patch_only: bool = Field(
        default=False, description="Enforce 'Patch, never regenerate' rule for file modifications"
    )


class CriticalityLevel(str, Enum):
    """Criticality / priority level for a subtask in the SDLC workflow."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RiskLevel(str, Enum):
    """Assessed risk level for code implementation or changes."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SpecStatus(str, Enum):
    """Lifecycle status for a technical subtask specification (sub-spec)."""

    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    TESTING = "testing"
    COMPLETED = "completed"
    BLOCKED = "blocked"


class FunctionSpec(BaseModel):
    """Specification of a function or method to be implemented."""

    name: str = Field(..., description="Function or method name")
    signature: str = Field(..., description="Complete python signature including type annotations")
    description: Optional[str] = Field(default=None, description="Detailed docstring or behavior")
    parameters: Dict[str, str] = Field(
        default_factory=dict, description="Parameter names mapped to their types/constraints"
    )
    return_type: str = Field(default="None", description="Expected return type annotation")
    raises: List[str] = Field(
        default_factory=list, description="Exceptions that the function is expected to raise"
    )


class TestCaseSpec(BaseModel):
    """Specification of a required test case to validate the implementation."""

    __test__ = False

    id: str = Field(..., description="Unique test case identifier (e.g. TC-01)")
    description: str = Field(..., description="Scenario and objective of the test")
    input_data: Dict[str, Any] = Field(
        default_factory=dict, description="Sample inputs or invocation parameters"
    )
    expected_output: Optional[Any] = Field(
        default=None, description="Expected return value or system state"
    )
    expected_exception: Optional[str] = Field(
        default=None, description="Expected exception class name if testing error path"
    )


class UntrustedSource(BaseModel):
    """External untrusted source (web page, PDF, issue, file) to be safely injected."""

    content: str = Field(..., description="Raw external text content")
    source_type: str = Field(
        default="web", description="Type of source: web, pdf, issue, file, etc."
    )
    source_id: Optional[str] = Field(default=None, description="Identifier, URL, or filepath")
    warning_instruction: Optional[str] = Field(
        default=None, description="Custom instruction override"
    )


class SubSpec(BaseModel):
    """Comprehensive technical specification for a subtask prior to execution."""

    criticality: CriticalityLevel = Field(
        default=CriticalityLevel.HIGH, description="Importance level of the subtask"
    )
    risk_level: RiskLevel = Field(
        default=RiskLevel.LOW, description="Assessed implementation risk level"
    )
    blast_radius: Optional[str] = Field(
        default=None, description="Scope of files, modules, or APIs affected"
    )
    risk_mitigation: Optional[str] = Field(
        default=None, description="Measures to avoid regressions or handle failures"
    )
    status: SpecStatus = Field(
        default=SpecStatus.APPROVED, description="Current lifecycle state of the spec"
    )
    functions: List[FunctionSpec] = Field(
        default_factory=list, description="Function / interface specifications to implement"
    )
    test_cases: List[TestCaseSpec] = Field(
        default_factory=list, description="Test cases required to achieve 100% pass rate"
    )
    acceptance_criteria: List[str] = Field(
        default_factory=list, description="SDLC quality gate criteria to satisfy"
    )


class SubTask(BaseModel):
    """A decomposed subtask to be executed by a designated worker agent."""

    id: str = Field(..., description="Unique subtask identifier")
    plan_id: Optional[str] = Field(
        default=None, description="Identifier of the parent orchestration plan"
    )
    name: str = Field(..., description="Human-readable subtask name")
    role: AgentRole = Field(
        default=AgentRole.CODER, description="Worker role responsible for this subtask"
    )
    instruction: str = Field(..., description="Detailed instructions for the worker agent")
    description: Optional[str] = Field(default=None, description="Detailed background or context")
    workspace_dir: Optional[str] = Field(
        default=None, description="Working directory for execution"
    )
    depends_on: List[str] = Field(
        default_factory=list, description="IDs of tasks that must complete before this starts"
    )
    checks: List[TaskCheck] = Field(
        default_factory=list, description="Validation checks to run after subtask finishes"
    )
    timeout_seconds: Optional[int] = Field(
        default=None, description="Override timeout for this subtask"
    )
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Current execution state")
    spec: Optional[SubSpec] = Field(
        default=None, description="Detailed SDLC technical specification (sub-spec)"
    )
    allowed_tools: Optional[List[str]] = Field(
        default=None, description="Override allowed tools for this subtask"
    )
    disallowed_tools: List[str] = Field(
        default_factory=list, description="Override disallowed tools for this subtask"
    )
    enforce_patch_only: Optional[bool] = Field(
        default=None, description="Override patch-only enforcement for this subtask"
    )
    tags: List[str] = Field(default_factory=list, description="Tags for categorization")
    plan_file: Optional[str] = Field(
        default=None,
        description="Path to specific subtask plan markdown file (e.g. .ai/plan/subtask_[id].md)",
    )
    plan_content: Optional[str] = Field(
        default=None,
        description="Explicit plan markdown content for this subtask",
    )
    interface_files: List[str] = Field(
        default_factory=list,
        description="Specific interface or schema files relevant to this task (e.g. models.py)",
    )
    interface_contents: Dict[str, str] = Field(
        default_factory=dict,
        description="In-memory interface file contents mapping path to code content",
    )
    external_sources: List[UntrustedSource] = Field(
        default_factory=list,
        description="Untrusted external sources (web pages, PDFs, issues) to inject into context",
    )


class OrchestrationPlan(BaseModel):
    """A master plan consisting of subtasks and worker configurations to achieve a goal."""

    plan_id: str = Field(..., description="Unique identifier for the orchestration plan")
    goal: str = Field(..., description="Overall goal or objective to be achieved")
    tasks: List[SubTask] = Field(
        default_factory=list, description="List of subtasks in the execution graph"
    )
    workers: Dict[str, WorkerAgentConfig] = Field(
        default_factory=dict, description="Worker configurations keyed by role or worker name"
    )
    stop_on_failure: bool = Field(
        default=True, description="Whether to abort remaining dependent tasks if a subtask fails"
    )
    enable_adversarial_critics: bool = Field(
        default=False,
        description=(
            "Whether to automatically dispatch parallel adversarial critics when Coder completes"
        ),
    )
    lazy_context: bool = Field(
        default=True,
        description="Enable lazy context loading: pass only assigned subtask spec and interfaces",
    )

    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)
        for task in self.tasks:
            if not task.plan_id and self.plan_id:
                task.plan_id = self.plan_id


class OrchestrationResult(BaseModel):
    """Outcome of an orchestration run with detailed status per subtask."""

    plan_id: str
    goal: str
    success: bool
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    duration_seconds: float
    task_results: Dict[str, RunResult] = Field(default_factory=dict)
    task_statuses: Dict[str, TaskStatus] = Field(default_factory=dict)
    critic_reviews: Dict[str, AggregatedCriticReview] = Field(
        default_factory=dict, description="Critic reviews indexed by subtask id"
    )
    summary: str = ""


RunResult.model_rebuild()
CriticFeedback.model_rebuild()
AggregatedCriticReview.model_rebuild()
OrchestrationResult.model_rebuild()
