"""Data models and schemas for Harness Agent."""

from __future__ import annotations

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
