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


class EvalReport(BaseModel):
    """Aggregated evaluation report across multiple tasks."""

    suite_name: str
    total_tasks: int
    passed_tasks: int
    failed_tasks: int
    duration_seconds: float
    pass_rate: float
    results: List[RunResult] = Field(default_factory=list)


class AgentRole(str, Enum):
    """Specialized roles for worker agents in the orchestrator architecture."""

    ORCHESTRATOR = "orchestrator"
    CODER = "coder"
    TESTER = "tester"
    REVIEWER = "reviewer"
    RESEARCHER = "researcher"


class TaskStatus(str, Enum):
    """Execution status for subtasks handled by the orchestrator."""

    PENDING = "pending"
    RUNNING = "running"
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


class SubTask(BaseModel):
    """A decomposed subtask to be executed by a designated worker agent."""

    id: str = Field(..., description="Unique subtask identifier")
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
    tags: List[str] = Field(default_factory=list, description="Tags for categorization")


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
    summary: str = ""
